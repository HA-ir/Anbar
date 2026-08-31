"""PERF-03: real image thumbnails generated at upload time.

Every gallery `<img>` used to pull the FULL object from Telegram storage —
a 50-photo gallery meant 50 complete downloads. Uploads of image objects now
also produce a small (≤256px) JPEG/WebP thumbnail next to the DB (no
Telethon round-trip at render time), served by `GET /f/{id}/thumb`.

Thumbnails are derived data: deleting the files is always safe (the endpoint
answers 404 and the UI falls back). Rebuild happens on the next upload of
the same image, or on demand via the harvester-free `_ensure` path used by
the thumb endpoint itself (single-flight, tiny CPU cost).
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
from pathlib import Path

from PIL import Image

log = logging.getLogger("anbar.thumbs")

THUMB_MAX_PX = 256
THUMB_FORMAT = "WebP"
THUMB_EXT = ".webp"
THUMB_QUALITY = 78
# generation happens in a thread; cap concurrent encodes
_SEM = asyncio.Semaphore(2)

SUPPORTED = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp", "image/tiff"}


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


def has_thumb(settings, obj_id: str) -> bool:
    try:
        base = _path(settings, obj_id)
        # RGB images are stored as JPEG, RGBA/WebP as WebP — check both
        return base.exists() or base.with_suffix(".jpg").exists()
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
            if im.mode not in ("RGB", "RGBA", "L"):
                im = im.convert("RGB")
            im.thumbnail((THUMB_MAX_PX, THUMB_MAX_PX), Image.Resampling.LANCZOS)
            if im.mode == "RGBA":
                tmp = out_webp.with_suffix(".webp.tmp")
                im.save(tmp, format=THUMB_FORMAT, quality=THUMB_QUALITY, method=4)
                os.replace(tmp, out_webp)
            else:
                tmp = out_jpg.with_suffix(".jpg.tmp")
                im.convert("RGB").save(tmp, format="JPEG", quality=THUMB_QUALITY)
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


async def generate(settings, obj_id: str, content_type: str, first_chunk: bytes) -> bool:
    """Generate a thumbnail from the first chunk of an image upload.

    Images smaller than one chunk arrive complete in `first_chunk`; a
    truncated tail only costs a little bottom-of-image quality (the encoder
    still produces a valid preview). Never raises.
    """
    if not first_chunk or (content_type or "").lower() not in SUPPORTED:
        return False
    out = _path(settings, obj_id)
    if out.exists():
        return True
    async with _SEM:
        if out.exists():  # single-flight: loser of the race just exits
            return True
        try:
            return await asyncio.to_thread(_encode, first_chunk, obj_id, settings)
        except Exception as e:  # noqa: BLE001
            log.debug("thumbnail generation error: %s", e)
            return False


def read_thumb(settings, obj_id: str) -> bytes | None:
    """Return thumbnail bytes, or None when missing/undecodable."""
    for p in (_path(settings, obj_id), _path(settings, obj_id).with_suffix(".jpg")):
        try:
            if p.exists():
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
