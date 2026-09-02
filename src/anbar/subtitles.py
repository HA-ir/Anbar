"""Video subtitle tracks (FEAT-SUBS): per-object SRT/VTT storage in kv.

Tracks are metadata of a video object, not standalone objects: they live in
kv under `subs:{obj_id}` as a JSON list and inherit the video's whole auth
matrix (cookie / bearer / signed link / password) through the /f/ download
auth path. A hard purge of the video drops the kv key with it.

Upload accepts SRT (converted to WebVTT on the way in — comma milliseconds,
BOM/CRLF quirks) or WebVTT. Cue text is sanitized: `<` that does not open a
whitelisted WebVTT inline tag is escaped, so a hostile subtitle file cannot
inject markup into player-driven UIs.
"""

from __future__ import annotations

import json
import re
import secrets
from typing import Any

MAX_SUB_BYTES = 2 * 1024 * 1024  # a subtitle is text; 2 MB is already absurd
MAX_TRACKS = 16
KV_PREFIX = "subs:"

_VTT_TAG_WHITELIST = re.compile(
    r"</?(?:i|b|u|v|c|ruby|rt|rp)(?:\s[^>\n]*)?>", re.IGNORECASE
)
_STRAY_TAG = re.compile(r"<[^>\n]{0,200}>")
# SRT timing line: 00:00:01,500 --> 00:00:03,000 (ms separator is a comma;
# some rips also use a dot or a colon — normalize all to the VTT dot)
_SRT_TS = re.compile(r"(\d{1,3}):(\d{2}):(\d{2})[,.:](\d{1,3})")
_TIMING_LINE = re.compile(r"-->")
_LANG_FROM_NAME = re.compile(
    r"[.\[ ]([a-zA-Z]{2,3}(?:-[a-zA-Z]{2,4})?)[.\]]?\.(srt|vtt)$", re.IGNORECASE
)


def _sanitize_vtt(text: str) -> str:
    """Escape `<...>` spans that are not whitelisted WebVTT inline tags."""

    def _sub(m: re.Match[str]) -> str:
        chunk = m.group(0)
        if _VTT_TAG_WHITELIST.fullmatch(chunk):
            return chunk
        return "&lt;" + chunk[1:-1] + "&gt;"

    return _STRAY_TAG.sub(_sub, text)


def _convert_srt(text: str) -> str:
    def _fix(m: re.Match[str]) -> str:
        h, mnt, s, ms = m.groups()
        return f"{int(h):02d}:{mnt}:{s}.{ms[:3].ljust(3, '0')}"

    out_lines = []
    for line in text.split("\n"):
        if _TIMING_LINE.search(line):
            line = _SRT_TS.sub(_fix, line)
        out_lines.append(line)
    return "WEBVTT\n\n" + "\n".join(out_lines).strip("\n") + "\n"


def parse_subtitle(filename: str, data: bytes) -> str:
    """Return sanitized WebVTT text for an uploaded SRT/VTT file.

    Raises ValueError with a short user-facing message on bad input.
    """
    if len(data) > MAX_SUB_BYTES:
        raise ValueError("subtitle file too large (max 2 MB)")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("subtitle must be UTF-8 text") from None
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    stripped = text.lstrip()
    if not stripped.startswith("WEBVTT"):
        # SRT (or an SRT missing its first counter) — requires at least one cue
        if "-->" not in text:
            raise ValueError("no cues found — not a valid SRT/VTT file")
        text = _convert_srt(text)
    text = _sanitize_vtt(text)
    if "-->" not in text:
        raise ValueError("no cues found — not a valid SRT/VTT file")
    return text


def _meta_from_filename(filename: str) -> tuple[str, str]:
    """(lang, label) derived from names like `movie.fa.srt` / `[en] title.vtt`."""
    name = (filename or "subtitle").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    m = _LANG_FROM_NAME.search(name)
    lang = ""
    if m:
        lang = m.group(1).lower()
        label = name[: m.start()].strip(".[ ") or name
    else:
        label = re.sub(r"\.(srt|vtt)$", "", name, flags=re.IGNORECASE)
    label = label.strip() or "subtitle"
    return lang, label


def load(db, obj_id: str) -> list[dict[str, Any]]:
    raw = db.kv_get(f"{KV_PREFIX}{obj_id}")
    if not raw:
        return []
    try:
        tracks = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return tracks if isinstance(tracks, list) else []


def _save(db, obj_id: str, tracks: list[dict[str, Any]]) -> None:
    db.kv_set(f"{KV_PREFIX}{obj_id}", json.dumps(tracks, ensure_ascii=False))


def public_view(tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": t["id"],
            "lang": t.get("lang", ""),
            "label": t.get("label", ""),
            "default": bool(t.get("default")),
        }
        for t in tracks
    ]


def add(db, obj_id: str, filename: str, data: bytes, default: bool = False) -> dict[str, Any]:
    tracks = load(db, obj_id)
    if len(tracks) >= MAX_TRACKS:
        raise ValueError(f"too many subtitle tracks (max {MAX_TRACKS})")
    vtt = parse_subtitle(filename, data)
    lang, label = _meta_from_filename(filename)
    entry = {
        "id": "s" + secrets.token_hex(4),
        "lang": lang,
        "label": label,
        "default": bool(default) or not tracks,  # first track is the default
        "vtt": vtt,
    }
    if entry["default"]:
        for t in tracks:
            t["default"] = False
    tracks.append(entry)
    _save(db, obj_id, tracks)
    return public_view([entry])[0]


def get_vtt(db, obj_id: str, track_id: str) -> str | None:
    for t in load(db, obj_id):
        if t["id"] == track_id:
            return t["vtt"]
    return None


def update(db, obj_id: str, track_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
    tracks = load(db, obj_id)
    target = None
    for t in tracks:
        if t["id"] == track_id:
            target = t
            break
    if target is None:
        return None
    if "label" in fields:
        label = str(fields["label"] or "").strip()
        if not label:
            raise ValueError("label must not be empty")
        target["label"] = label[:80]
    if "lang" in fields:
        target["lang"] = str(fields["lang"] or "").strip().lower()[:16]
    if "default" in fields and bool(fields["default"]):
        for t in tracks:
            t["default"] = False
        target["default"] = True
    _save(db, obj_id, tracks)
    return public_view([target])[0]


def delete(db, obj_id: str, track_id: str) -> bool:
    tracks = load(db, obj_id)
    deleted = None
    remaining = []
    for t in tracks:
        if t["id"] == track_id:
            deleted = t
        else:
            remaining.append(t)
    if deleted is None:
        return False
    if deleted.get("default") and remaining:
        # deleted the default → fall back to the first remaining track
        for t in remaining:
            t["default"] = False
        remaining[0]["default"] = True
    _save(db, obj_id, remaining)
    return True


def drop_for(db, obj_id: str) -> None:
    db.kv_delete(f"{KV_PREFIX}{obj_id}")
