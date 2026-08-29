from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

from .crypto import decrypt_gcm, derive_key_256, encrypt_gcm
from .db import Database
from .objects import Chunk, Manifest

log = logging.getLogger("anbar.self_healing")

CAPTION_PREFIX = "anbar:v1:"
EVENT_PREFIX = "anbar:v1:evt:"


def encode_chunk_caption(
    obj_id: str,
    chunk_idx: int,
    total_chunks: int,
    filename: str,
    total_size: int,
    content_type: str | None = None,
    sha256: str | None = None,
    secret: str | None = None,
) -> str:
    """Pack and encrypt chunk metadata into a compact Telegram message caption."""
    meta = {
        "id": obj_id,
        "i": chunk_idx,
        "n": total_chunks,
        "fn": filename,
        "sz": total_size,
        "ct": content_type or "",
        "h": (sha256 or "")[:16],  # first 16 hex chars of hash to save space
        "ts": int(time.time()),
    }
    raw_bytes = json.dumps(meta, separators=(",", ":")).encode("utf-8")
    if secret:
        key = derive_key_256(secret)
        enc = encrypt_gcm(raw_bytes, key)
        b64 = base64.urlsafe_b64encode(enc).decode("ascii").rstrip("=")
        return f"{CAPTION_PREFIX}e:{b64}"
    else:
        b64 = base64.urlsafe_b64encode(raw_bytes).decode("ascii").rstrip("=")
        return f"{CAPTION_PREFIX}p:{b64}"


def decode_chunk_caption(caption: str | None, secret: str | None = None) -> dict[str, Any] | None:
    """Decode and decrypt a chunk metadata caption envelope."""
    if not caption or not isinstance(caption, str):
        return None
    caption = caption.strip()
    if not caption.startswith(CAPTION_PREFIX):
        return None

    envelope = caption[len(CAPTION_PREFIX) :]
    if envelope.startswith("e:"):
        if not secret:
            log.debug("encrypted caption found but no secret provided")
            return None
        b64_str = envelope[2:]
        # restore padding
        b64_str += "=" * (-len(b64_str) % 4)
        try:
            enc_bytes = base64.urlsafe_b64decode(b64_str)
            key = derive_key_256(secret)
            dec_bytes = decrypt_gcm(enc_bytes, key)
            return json.loads(dec_bytes.decode("utf-8"))
        except Exception as e:
            log.debug("failed decrypting caption envelope: %s", e)
            return None

    elif envelope.startswith("p:"):
        b64_str = envelope[2:]
        b64_str += "=" * (-len(b64_str) % 4)
        try:
            raw_bytes = base64.urlsafe_b64decode(b64_str)
            return json.loads(raw_bytes.decode("utf-8"))
        except Exception as e:
            log.debug("failed decoding plain caption envelope: %s", e)
            return None

    return None


def encode_meta_event(event: dict[str, Any], secret: str | None = None) -> str:
    """Encode and optionally encrypt a meta event message (rename, delete, move)."""
    if "ts" not in event:
        event["ts"] = int(time.time())
    raw_bytes = json.dumps(event, separators=(",", ":")).encode("utf-8")
    if secret:
        key = derive_key_256(secret)
        enc = encrypt_gcm(raw_bytes, key)
        b64 = base64.urlsafe_b64encode(enc).decode("ascii").rstrip("=")
        return f"{EVENT_PREFIX}e:{b64}"
    else:
        b64 = base64.urlsafe_b64encode(raw_bytes).decode("ascii").rstrip("=")
        return f"{EVENT_PREFIX}p:{b64}"


def decode_meta_event(text: str | None, secret: str | None = None) -> dict[str, Any] | None:
    """Decode and decrypt a meta event message from Telegram channel."""
    if not text or not isinstance(text, str):
        return None
    text = text.strip()
    if not text.startswith(EVENT_PREFIX):
        return None

    envelope = text[len(EVENT_PREFIX) :]
    if envelope.startswith("e:"):
        if not secret:
            return None
        b64_str = envelope[2:]
        b64_str += "=" * (-len(b64_str) % 4)
        try:
            enc_bytes = base64.urlsafe_b64decode(b64_str)
            key = derive_key_256(secret)
            dec_bytes = decrypt_gcm(enc_bytes, key)
            return json.loads(dec_bytes.decode("utf-8"))
        except Exception as e:
            log.debug("failed decrypting meta event: %s", e)
            return None
    elif envelope.startswith("p:"):
        b64_str = envelope[2:]
        b64_str += "=" * (-len(b64_str) % 4)
        try:
            raw_bytes = base64.urlsafe_b64decode(b64_str)
            return json.loads(raw_bytes.decode("utf-8"))
        except Exception as e:
            log.debug("failed decoding plain meta event: %s", e)
            return None

    return None


async def emit_meta_event(backend: Any, event: dict[str, Any], secret: str | None = None) -> None:
    """Emit a background meta event to the Telegram channel."""
    if not backend or not hasattr(backend, "send_text_event"):
        return
    try:
        text = encode_meta_event(event, secret=secret)
        await backend.send_text_event(text)
    except Exception as e:
        log.warning("failed emitting meta event to channel: %s", e)


def replay_meta_events(events: list[dict[str, Any]], db: Database) -> int:
    """Replay collected journal events (folder renames, file renames, deletes)."""
    # Sort events by timestamp ascending
    sorted_events = sorted(events, key=lambda e: e.get("ts", 0))
    applied = 0
    for evt in sorted_events:
        op = evt.get("op")
        if op == "rn_dir":
            old_p = evt.get("old", "")
            new_p = evt.get("new", "")
            if old_p and new_p:
                db.rename_folder(old_p, new_p)
                applied += 1
        elif op == "rn_obj":
            obj_id = evt.get("id", "")
            new_fn = evt.get("new", "")
            if obj_id and new_fn:
                db.rename_object(obj_id, new_fn)
                applied += 1
        elif op == "mv_obj":
            obj_ids = evt.get("ids", [])
            dest = evt.get("dest", "")
            if obj_ids:
                db.move_objects_to_prefix(obj_ids, dest)
                applied += 1
        elif op == "del_obj":
            obj_id = evt.get("id", "")
            if obj_id:
                db.delete_object(obj_id)
                applied += 1
        elif op == "del_batch":
            obj_ids = evt.get("ids", [])
            for oid in obj_ids:
                if oid:
                    db.delete_object(str(oid))
                    applied += 1
    return applied


def rebuild_from_manifests(
    collected_chunks: dict[str, list[dict[str, Any]]],
    db: Database,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Reconstruct Database objects from grouped chunks and replay journal events."""
    recovered = 0
    skipped = 0
    incomplete = 0

    for obj_id, chunks_meta in collected_chunks.items():
        if not chunks_meta:
            continue

        first = chunks_meta[0]["meta"]
        filename = first.get("fn", f"recovered_{obj_id}")
        content_type = first.get("ct") or "application/octet-stream"
        created_at = first.get("ts", int(time.time()))
        total_expected_chunks = first.get("n", len(chunks_meta))
        total_size = first.get("sz", sum(c.get("size", 0) for c in chunks_meta))

        # Check completeness if total_chunks was specified (> 0)
        if total_expected_chunks > 0 and len(chunks_meta) < total_expected_chunks:
            log.warning(
                "object %s has %d chunks but expected %d — skipping",
                obj_id,
                len(chunks_meta),
                total_expected_chunks,
            )
            incomplete += 1
            continue

        # Sort chunks by index
        sorted_chunks = sorted(chunks_meta, key=lambda c: c["meta"].get("i", 0))

        # Check if already in DB
        existing = db.get_object(obj_id, include_trashed=True)
        if existing:
            skipped += 1
            continue

        manifest_chunks = []
        for c in sorted_chunks:
            manifest_chunks.append(
                Chunk(
                    index=c["meta"].get("i", 0),
                    size=c.get("size", 0),
                    file_id=c.get("file_id", ""),
                    message_id=c.get("message_id"),
                    bot_file_id=c.get("bot_file_id"),
                )
            )

        manifest = Manifest(chunks=manifest_chunks, total_size=total_size)
        db.insert_object(
            {
                "id": obj_id,
                "file_id": manifest.chunks[0].file_id,
                "backend": sorted_chunks[0].get("backend", "bot"),
                "filename": filename,
                "size": total_size,
                "content_type": content_type,
                "sha256": first.get("h", ""),
                "manifest": manifest.to_json(),
                "created_at": created_at,
                "uploader_key": "recovered",
            }
        )
        recovered += 1

    # Replay journal events if provided
    events_applied = 0
    if events:
        events_applied = replay_meta_events(events, db)

    return {
        "recovered_objects": recovered,
        "skipped_existing": skipped,
        "incomplete_objects": incomplete,
        "events_replayed": events_applied,
        "total_groups_scanned": len(collected_chunks),
        "total_chunks_scanned": sum(len(v) for v in collected_chunks.values()),
    }
