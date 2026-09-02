"""FEAT-SUBS-2: import subtitle tracks embedded in video containers (MKV/MP4).

Browser players cannot read soft-sub tracks inside an MKV — the tracks must
be extracted server-side and served as WebVTT sidecars. This module:

1. probes a video object with ffprobe for embedded subtitle streams
   (the Matroska/MP4 track headers sit in the first chunks, so probing
   needs only the head of the file);
2. extracts each SRT/ASS→SRT stream with ``ffmpeg -c:s srt`` (stream copy —
   near-zero CPU, no re-encode) and imports the result through
   :mod:`anbar.subtitles` (same kv storage, sanitization, WebVTT serving).

ffmpeg/ffprobe are optional: when missing, ``AVAILABLE`` is False and every
entry point is a no-op, so the feature degrades silently everywhere (tests,
fake backends, minimal installs).
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from . import subtitles

log = logging.getLogger("anbar.subs_extract")

# past this many embedded tracks something is wrong — cap like manual tracks
MAX_EMBEDDED = 8
# one-shot guard: an object is auto-imported at most once
DONE_PREFIX = "subsimported:"

AVAILABLE = shutil.which("ffprobe") is not None and shutil.which("ffmpeg") is not None

FetchChunk = Callable[[str, int, int, int], Awaitable[bytes]]


def video_ext(filename: str) -> bool:
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    return ext in {"mp4", "webm", "mkv", "mov", "avi", "m4v", "ogv", "ts"}


def _tmp_root(settings) -> Path:  # noqa: ANN001
    d = Path(settings.data_dir) / "tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def probe_bytes(head: bytes) -> list[dict[str, Any]]:
    """ffprobe the first bytes of a video; return text subtitle streams.

    `head` is written to a temp file because ffprobe wants seekable input.
    """
    if not AVAILABLE or not head:
        return []
    tmpdir = Path(tempfile.mkdtemp(prefix="subsprobe-"))
    try:
        f = tmpdir / "head.bin"
        f.write_bytes(head)
        res = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(f)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if res.returncode != 0:
            return []
        try:
            data = json.loads(res.stdout)
        except json.JSONDecodeError:
            return []
        return _text_sub_streams(data)
    except Exception:  # noqa: BLE001 — any probe failure means "no subs found"
        return []
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _text_sub_streams(data: dict[str, Any]) -> list[dict[str, Any]]:
    streams = []
    for s in data.get("streams", []):
        if s.get("codec_type") != "subtitle":
            continue
        # only text-based subs can be cheaply converted; bitmap subs
        # (dvdsub/pgssub/hdmv_pgs_subtitle) would need OCR — skip them
        if s.get("codec_name") not in ("subrip", "srt", "ass", "ssa", "webvtt", "mov_text"):
            continue
        tags = s.get("tags") or {}
        streams.append(
            {
                "index": int(s["index"]),
                "codec": s.get("codec_name"),
                "lang": str(tags.get("language", "")).lower(),
                "title": str(tags.get("title", "")),
            }
        )
    return streams


def extract_stream_to_srt(video: Path, stream_index: int, out_srt: Path) -> bool:
    """ffmpeg stream-copy one subtitle stream to SRT (no re-encode, ~0 CPU)."""
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error", "-i", str(video),
                "-map", f"0:{stream_index}", "-c:s", "srt", str(out_srt),
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except Exception:  # noqa: BLE001
        return False
    return out_srt.exists() and out_srt.stat().st_size > 0


def _lang_name(lang: str, title: str, idx: int) -> str:
    lang = (lang or "").strip()
    if lang == "per":  # ISO 639-2 for Persian → our fa convention
        lang = "fa"
    base = "embedded" if lang else f"embedded-{idx}"
    if title:
        safe = "".join(ch for ch in title if ch.isalnum() or ch in " ._-")[:40].strip()
        if safe:
            base += f" {safe}"
    return base + ".srt"


async def _gather_all_chunks(
    obj_id: str, manifest: dict[str, Any], fetch_chunk: FetchChunk, dest: Path
) -> int:
    """Pull every chunk of the object into `dest`; return bytes written."""
    total = 0
    with dest.open("wb") as f:
        for c in manifest.get("chunks", []):
            data = await fetch_chunk(obj_id, c["i"], 0, c["s"])
            f.write(data)
            total += len(data)
    return total


async def import_embedded(
    db,
    settings,
    obj_id: str,
    manifest: dict[str, Any],
    fetch_chunk: FetchChunk,
    *,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Extract embedded subtitle tracks of a video object and register them.

    Never raises: failures are logged and return the (possibly empty) list of
    tracks imported so far. Skips when the one-shot flag is set unless force.
    """
    if not AVAILABLE or not video_ext(_filename_of(db, obj_id)):
        return []
    if not force and db.kv_get(f"{DONE_PREFIX}{obj_id}"):
        return []
    db.kv_set(f"{DONE_PREFIX}{obj_id}", "1")

    tmpdir = Path(tempfile.mkdtemp(prefix="subsx-", dir=_tmp_root(settings)))
    added: list[dict[str, Any]] = []
    try:
        video = tmpdir / "video.bin"
        try:
            await asyncio.wait_for(
                _gather_all_chunks(obj_id, manifest, fetch_chunk, video), timeout=900
            )
        except Exception:  # noqa: BLE001 — partial file may still probe fine
            log.warning("embedded-subs: chunk gather incomplete for %s", obj_id)
        if not video.exists() or video.stat().st_size == 0:
            return []

        # probe on a background thread (blocking subprocess)
        probe_res = await asyncio.to_thread(_probe_file, video)
        if not probe_res:
            return []

        existing_langs = {t.get("lang") for t in subtitles.load(db, obj_id)}
        existing_labels = {t.get("label") for t in subtitles.load(db, obj_id)}
        for st in probe_res[:MAX_EMBEDDED]:
            # normalize before dedupe: ISO 639-2 "per" must match our "fa"
            eff_lang = "fa" if st["lang"] == "per" else st["lang"]
            if eff_lang and eff_lang in existing_langs:
                continue  # a track with this language already exists
            out_srt = tmpdir / f"out-{st['index']}.srt"
            ok = await asyncio.to_thread(extract_stream_to_srt, video, st["index"], out_srt)
            if not ok:
                continue
            try:
                data = out_srt.read_bytes()
                fname = _lang_name(st["lang"], st["title"], st["index"])
                label = fname[: -len(".srt")]
                if label in existing_labels:
                    continue  # racing importer already added this exact track
                view = subtitles.add(
                    db,
                    obj_id,
                    fname,
                    data,
                    lang=eff_lang,
                )
                added.append(view)
                existing_langs.add(eff_lang)
                existing_labels.add(label)
            except ValueError as e:
                log.info("embedded track %s/%s skipped: %s", obj_id, st["index"], e)
        if added:
            log.info("embedded-subs: imported %d track(s) for %s", len(added), obj_id)
        return added
    except Exception:  # noqa: BLE001 — best-effort by design
        log.exception("embedded-subs import failed for %s", obj_id)
        return added
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _probe_file(video: Path) -> list[dict[str, Any]]:
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(video)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception:  # noqa: BLE001
        return []
    if res.returncode != 0:
        return []
    try:
        return _text_sub_streams(json.loads(res.stdout))
    except json.JSONDecodeError:
        return []


def _filename_of(db, obj_id: str) -> str:  # noqa: ANN001
    row = db.get_object(obj_id)
    return str(row["filename"]) if row else ""
