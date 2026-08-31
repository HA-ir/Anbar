"""ObjectService — single home for chunk store/rollback/commit (QUAL-01).

Both `api/upload.py` (`_store_stream`/`_commit`) and `api/ingest.py`
(`_run_job`) used to carry copy-pasted rollback + commit blocks that had
already drifted (captions/harvester/checkpoint only on the upload path).
This service is the shared implementation; the routes keep their own
HTTP/job semantics on top.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from . import runtime
from .auth import effective_hmac_secret
from .objects import Chunk, Manifest, chunk_stream, new_object_id, opaque_chunk_name
from .self_healing import encode_chunk_caption
from .storage import FloodBudgetExceeded, ObjectRef, TelegramError

log = logging.getLogger("anbar.objectsvc")


class ObjectService:
    """Stores a stream as chunked Telegram blobs and commits the manifest.

    One instance per upload/ingest run (it owns exactly one manifest).
    """

    def __init__(
        self,
        *,
        backend,
        db,
        settings,
        filename: str,
        content_type: str | None = None,
        upload_id: str | None = None,
        resume_from: int = 0,
        checkpoint_prefix: str = "upres",
    ) -> None:
        self.backend = backend
        self.db = db
        self.settings = settings
        self.filename = filename
        self.content_type = content_type
        self.upload_id = upload_id
        self.manifest = Manifest(chunks=[], total_size=0)
        # PERF-03: first chunk is kept aside for thumbnail generation
        self.first_chunk: bytes = b""
        # checkpointing is optional: the upload path resumes, ingest does not
        self.ck_key = f"{checkpoint_prefix}:{upload_id}" if upload_id else None
        self.resume_from = resume_from if self.ck_key else 0
        self.skip_remaining = self.resume_from
        self.harvester = None  # optionally wired by the caller

    # ------------------------------------------------------------------ ckpt
    def _load_prior_chunks(self) -> list[dict]:
        if not (self.ck_key and self.resume_from):
            return []
        try:
            raw = json.loads(self.db.kv_get(self.ck_key, "") or "")  # envelope
            prior = raw.get("chunks", []) if isinstance(raw, dict) else raw
        except (json.JSONDecodeError, AttributeError):
            prior = []
        if self.resume_from > len(prior):
            raise ResumeOutOfRange(
                f"cannot resume from {self.resume_from}: only {len(prior)} "
                "chunks are checkpointed for this upload id"
            )
        return prior[: self.resume_from]

    def _write_checkpoint(self) -> None:
        if not self.ck_key:
            return
        self.db.kv_set(
            self.ck_key,
            json.dumps(
                {
                    # _ts lets kv_prune_prefix drop checkpoints abandoned
                    # mid-upload (older than 24h) without a schema change
                    "_ts": int(time.time()),
                    "chunks": [
                        {"s": c.size, "f": c.file_id, "m": c.message_id}
                        for c in self.manifest.chunks
                    ],
                },
                separators=(",", ":"),
            ),
        )

    def drop_checkpoint(self) -> None:
        """Called after a successful commit — closes the MP-02 leak."""
        if self.ck_key:
            self.db.kv_delete(self.ck_key)

    # ----------------------------------------------------------------- store
    async def store_stream(self, stream) -> tuple[Manifest, str]:
        """Drive the chunker over `stream`; return (manifest, sha256_hex).

        Rolls back posted blobs on any failure, then re-raises.
        """
        prior = self._load_prior_chunks()
        # pre-seed the manifest with already-stored chunks (resume)
        for i, c in enumerate(prior):
            self.manifest.chunks.append(
                Chunk(index=i, size=c["s"], file_id=c["f"], message_id=c.get("m"))
            )

        configured_sec = (
            self.settings.hmac_secret.get_secret_value() if self.settings.hmac_secret else None
        )
        active_secret = effective_hmac_secret(self.db, configured_sec)

        async def on_chunk(data: bytes, media: bool = False) -> str:
            if self.skip_remaining > 0:
                self.skip_remaining -= 1  # duplicate of an stored chunk: drain
                return ""
            if not self.first_chunk:
                self.first_chunk = data  # PERF-03: kept for thumb generation
            chunk_idx = len(self.manifest.chunks)
            caption = encode_chunk_caption(
                obj_id=self.upload_id or "",
                chunk_idx=chunk_idx,
                total_chunks=0,
                filename=self.filename,
                total_size=0,
                content_type=self.content_type,
                secret=active_secret,
            )
            ref = await self.backend.store(
                data,
                opaque_chunk_name(chunk_idx),
                content_type=None,
                caption=caption,
            )
            bot_fid = None
            if self.harvester and ref.message_id is not None:
                try:
                    bot_fid = await self.harvester.get_file_id_for_message(
                        ref.message_id, timeout=2.0
                    )
                except Exception as e:  # noqa: BLE001
                    log.debug("harvester error for msg %s: %s", ref.message_id, e)
            self.manifest.chunks.append(
                Chunk(
                    index=chunk_idx,
                    size=len(data),
                    file_id=ref.file_id,
                    message_id=ref.message_id,
                    bot_file_id=bot_fid,
                )
            )
            self._write_checkpoint()
            return ref.file_id

        try:
            _, sha_hex = await chunk_stream(
                stream,
                self.settings.chunk_size,
                on_chunk,
                # ingest passes content_type=None → no media hint, identical
                # to the old ingest `put()` path
                is_first_chunk_media=bool(self.content_type),
            )
        except BaseException:
            await self.rollback()
            raise
        return self.manifest, sha_hex

    async def rollback(self) -> int:
        """Best-effort delete of every blob posted so far. Never raises."""
        deleted = 0
        for c in self.manifest.chunks:
            try:
                await self.backend.delete(
                    ObjectRef(
                        file_id=c.file_id,
                        message_id=c.message_id,
                        backend=self.backend.name,
                    )
                )
                deleted += 1
            except Exception:  # noqa: BLE001
                pass
        return deleted

    # ---------------------------------------------------------------- commit
    def commit(self, *, sha_hex: str, uploader_key: str | None = None) -> str:
        """Insert the object row; returns obj_id. Returns before checkpoint
        cleanup — call `drop_checkpoint()` once the response is on its way."""
        self.manifest.total_size = sum(c.size for c in self.manifest.chunks)
        obj_id = new_object_id()
        self.db.insert_object(
            {
                "id": obj_id,
                "file_id": self.manifest.chunks[0].file_id,
                "backend": self.backend.name,
                "filename": self.filename,
                "size": self.manifest.total_size,
                "content_type": self.content_type or "application/octet-stream",
                "sha256": sha_hex,
                "manifest": self.manifest.to_json(),
                "uploader_key": uploader_key,
            }
        )
        return obj_id


class ResumeOutOfRange(Exception):
    """X-Resume-From points past the checkpointed chunks (HTTP 409 upstream)."""


def describe_storage_error(e: BaseException) -> tuple[int, str]:
    """Map backend exceptions to (status, detail) — shared by both routes."""
    if isinstance(e, FloodBudgetExceeded):
        return 504, f"telegram: {e.message}"
    if isinstance(e, TelegramError):
        return 502, f"telegram: {e.message}"
    return 502, f"storage error: {e}"
