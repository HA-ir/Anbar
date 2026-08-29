"""v0.15.1: Self-Describing & Self-Healing Encrypted Storage (Disaster Recovery).

Embeds compact, encrypted zero-knowledge metadata envelopes into Telegram
chunk captions and allows full database reconstruction directly from channel
history even if the entire local SQLite database is lost.
"""

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
    """Decode and decrypt a chunk caption envelope from a Telegram message."""
    if not caption or not isinstance(caption, str) or not caption.startswith(CAPTION_PREFIX):
        return None
    payload = caption[len(CAPTION_PREFIX) :]
    if not payload or ":" not in payload:
        return None
    kind, b64_data = payload.split(":", 1)
    # Fix base64 padding
    missing_padding = len(b64_data) % 4
    if missing_padding:
        b64_data += "=" * (4 - missing_padding)

    try:
        data = base64.urlsafe_b64decode(b64_data.encode("ascii"))
    except Exception as e:
        log.debug("Base64 decode failed for caption envelope: %s", e)
        return None

    if kind == "e":
        if not secret:
            log.warning("Encrypted caption found but no secret key provided")
            return None
        try:
            key = derive_key_256(secret)
            raw = decrypt_gcm(data, key)
            return json.loads(raw.decode("utf-8"))
        except Exception as e:
            log.warning("Failed to decrypt caption envelope with secret: %s", e)
            return None
    elif kind == "p":
        try:
            return json.loads(data.decode("utf-8"))
        except Exception as e:
            log.warning("Failed to parse plain caption envelope: %s", e)
            return None
    return None


def rebuild_from_manifests(
    collected_chunks: dict[str, list[dict[str, Any]]],
    db: Database,
) -> dict[str, Any]:
    """Assemble chunks and insert reconstructed objects into the database."""
    recovered = 0
    skipped = 0
    incomplete = 0

    for obj_id, chunks_meta in collected_chunks.items():
        if not chunks_meta:
            continue
        first = chunks_meta[0]["meta"]
        expected_total_chunks = first.get("n", 1)
        filename = first.get("fn", f"recovered_{obj_id}.bin")
        total_size = first.get("sz", 0)
        content_type = first.get("ct") or None
        created_at = first.get("ts", int(time.time()))

        # Check if we have all chunks
        present_indices = {c["meta"].get("i", 0) for c in chunks_meta}
        if len(present_indices) < expected_total_chunks:
            log.warning(
                "Object %s is incomplete: got %d/%d chunks (indices: %s)",
                obj_id,
                len(present_indices),
                expected_total_chunks,
                sorted(present_indices),
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

    return {
        "recovered_objects": recovered,
        "skipped_existing": skipped,
        "incomplete_objects": incomplete,
        "total_groups_scanned": len(collected_chunks),
        "total_chunks_scanned": sum(len(v) for v in collected_chunks.values()),
    }
