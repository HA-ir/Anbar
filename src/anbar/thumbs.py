"""PERF-03 / BUG-38: real image and video thumbnails generated at upload time.

Every gallery `<img>` used to pull the FULL object from Telegram storage —
a 50-photo gallery meant 50 complete downloads. Uploads of image and video objects
produce a small (≤256px) JPEG/WebP thumbnail next to the DB (no
Telethon round-trip at render time), served by `GET /f/{id}/thumb`.

Video poster extraction captures a representative frame via ffmpeg and stores
it as a lightweight static WebP image.

Thumbnails are derived data: deleting the files is always safe (the endpoint
answers 404 and the UI falls back). Rebuild happens on the next upload of
the same media, or on demand via the thumb endpoint itself.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import shutil
import subprocess
from pathlib import Path

from PIL import Image

log = logging.getLogger("anbar.thumbs")

THUMB_MAX_PX = 256
THUMB_FORMAT = "WebP"
THUMB_EXT = ".webp"
THUMB_QUALITY = 78
# generation happens in a thread; cap concurrent encodes
_SEM = asyncio.Semaphore(2)

SUPPORTED_IMAGE = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/bmp",
    "image/tiff",
}
SUPPORTED_VIDEO = {
    "video/mp4",
    "video/x-matroska",
    "video/webm",
    "video/quicktime",
}
SUPPORTED = SUPPORTED_IMAGE | SUPPORTED_VIDEO

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None


def is_video(content_type: str | None) -> bool:
    """True when this content type is a supported video format."""
    return (content_type or "").lower() in SUPPORTED_VIDEO


def SUPPORTED_OK(content_type: str | None) -> bool:
    """True when this content type gets a thumbnail."""
    return (content_type or "").lower() in SUPPORTED


def thumbs_dir(settings) -> Path:
    d = Path(settings.data_dir) / "thumbs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(settings, obj_id: str) -> Path:
    # obj_id is server-generated base62; the suffix guards against any future
    # id scheme containing path separators
    safe = "".join(c for c in obj_id if c.isalnum() or c in "-_")[:64] or "x"
    return thumbs_dir(settings) / f"{safe}{THUMB_EXT}"


def has_thumb(settings, obj_id: str, content_type: str | None = None) -> bool:
    try:
        base = _path(settings, obj_id)
        # RGB images are stored as JPEG, RGBA/WebP and video as WebP — check both
        if base.exists() or base.with_suffix(".jpg").exists():
            return True
        if content_type and is_video(content_type) and FFMPEG_AVAILABLE:
            return True
        return False
    except OSError:
        return False


def _encode(original: bytes, obj_id: str, settings) -> bool:
    """Decode + downscale + encode. Returns False for non-decodable input."""
    out_webp = _path(settings, obj_id)
    out_jpg = out_webp.with_suffix(".jpg")
    try:
        with Image.open(io.BytesIO(original)) as im:
            im.load()
            if getattr(im, "is_animated", False):
                im.seek(0)  # first frame only
            im_thumb: Image.Image = (
                im.convert("RGB") if im.mode not in ("RGB", "RGBA", "L") else im
            )
            im_thumb.thumbnail((THUMB_MAX_PX, THUMB_MAX_PX), Image.Resampling.LANCZOS)
            if im_thumb.mode == "RGBA":
                tmp = out_webp.with_suffix(".webp.tmp")
                im_thumb.save(tmp, format=THUMB_FORMAT, quality=THUMB_QUALITY, method=4)
                os.replace(tmp, out_webp)
            else:
                tmp = out_jpg.with_suffix(".jpg.tmp")
                im_thumb.convert("RGB").save(tmp, format="JPEG", quality=THUMB_QUALITY)
                os.replace(tmp, out_jpg)
            return True
    except Exception as e:  # noqa: BLE001 — corrupt/unsupported image must not break upload
        log.debug("thumbnail encode failed: %s", e)
        # remove half-written tmp files if any
        for p in (out_webp.with_suffix(".webp.tmp"), out_jpg.with_suffix(".jpg.tmp")):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        return False


def _encode_video(source: bytes | Path, obj_id: str, settings) -> bool:
    """Extract a video frame using ffmpeg into WebP. Returns False on failure."""
    if not FFMPEG_AVAILABLE:
        return False
    out_webp = _path(settings, obj_id)
    tmp_webp = out_webp.with_suffix(".tmp.webp")
    in_temp: Path | None = None
    try:
        if isinstance(source, (str, Path)):
            in_file = Path(source)
        else:
            d = thumbs_dir(settings)
            in_temp = d / f"{obj_id}_in.tmp"
            in_temp.write_bytes(source)
            in_file = in_temp

        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            "00:00:01",
            "-i",
            str(in_file),
            "-vframes",
            "1",
            "-vf",
            f"scale='min({THUMB_MAX_PX},iw)':-1",
            "-c:v",
            "libwebp",
            "-quality",
            str(THUMB_QUALITY),
            "-f",
            "webp",
            str(tmp_webp),
        ]
        subprocess.run(cmd, capture_output=True, timeout=15)
        if not tmp_webp.exists() or tmp_webp.stat().st_size == 0:
            # Fallback to 00:00:00 if seeking to 1s yielded no frame
            cmd[3] = "00:00:00"
            subprocess.run(cmd, capture_output=True, timeout=15)

        if tmp_webp.exists() and tmp_webp.stat().st_size > 0:
            os.replace(tmp_webp, out_webp)
            return True
        return False
    except Exception as e:  # noqa: BLE001
        log.debug("video thumbnail extraction failed for %s: %s", obj_id, e)
        return False
    finally:
        if in_temp is not None:
            try:
                in_temp.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            tmp_webp.unlink(missing_ok=True)
        except OSError:
            pass


async def generate(settings, obj_id: str, content_type: str, first_chunk: bytes) -> bool:
    """Generate a thumbnail from the first chunk of an image or video upload.

    Images smaller than one chunk arrive complete in `first_chunk`; a
    truncated tail only costs a little bottom-of-image quality (the encoder
    still produces a valid preview). Never raises.
    """
    ct = (content_type or "").lower()
    if not first_chunk or ct not in SUPPORTED:
        return False
    out = _path(settings, obj_id)
    if out.exists():
        return True
    async with _SEM:
        if out.exists():  # single-flight: loser of the race just exits
            return True
        try:
            if is_video(ct):
                return await asyncio.to_thread(_encode_video, first_chunk, obj_id, settings)
            return await asyncio.to_thread(_encode, first_chunk, obj_id, settings)
        except Exception as e:  # noqa: BLE001
            log.debug("thumbnail generation error: %s", e)
            return False


def read_thumb(settings, obj_id: str) -> bytes | None:
    """Return thumbnail bytes, or None when missing/undecodable."""
    for p in (_path(settings, obj_id), _path(settings, obj_id).with_suffix(".jpg")):
        try:
            if p.exists() and p.stat().st_size > 0:
                return p.read_bytes()
        except OSError:
            continue
    return None


def delete_thumb(settings, obj_id: str) -> None:
    """Best-effort cleanup on object delete/purge."""
    for p in (_path(settings, obj_id), _path(settings, obj_id).with_suffix(".jpg")):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
