"""Upload endpoints (F2). Multipart + raw streaming, chunked, manifest-backed.

Auth is enforced by the middleware layer (F4); F2 records the uploader for
ownership (used by DELETE in F4).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from .. import runtime
from ..auth import effective_hmac_secret, require_uploader
from ..objects import Chunk, Manifest, chunk_stream, new_object_id, opaque_chunk_name
from ..ratelimit import limit_upload
from ..self_healing import encode_chunk_caption
from ..storage import FloodBudgetExceeded, ObjectRef, TelegramError

router = APIRouter()
log = logging.getLogger("anbar.upload")


class BodyReadTimeout(Exception):
    """Client stopped sending the body it declared (Content-Length)."""


def _uploader_key(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:]
    return None


def _rate_upload(request: Request) -> int:
    s = request.app.state.settings
    return runtime.get_int(request.app.state.db, "rate_upload", s.rate_upload_per_min)


def _max_upload_bytes(request: Request) -> int:
    s = request.app.state.settings
    mb = runtime.get_int(request.app.state.db, "max_upload_mb", s.max_upload_mb)
    return mb * 1024 * 1024


async def _commit(
    request: Request, manifest: Manifest, sha_hex: str, filename: str, content_type: str
) -> JSONResponse:
    settings = request.app.state.settings
    backend = request.app.state.backend
    db = request.app.state.db
    manifest.total_size = sum(c.size for c in manifest.chunks)
    obj_id = new_object_id()
    db.insert_object(
        {
            "id": obj_id,
            "file_id": manifest.chunks[0].file_id,
            "backend": backend.name,
            "filename": filename,
            "size": manifest.total_size,
            "content_type": content_type,
            "sha256": sha_hex,
            "manifest": manifest.to_json(),
            "uploader_key": _uploader_key(request),
        }
    )
    # resume checkpoint no longer needed once the object is committed —
    # without this the upres:<id> rows accumulate in kv forever (MP-02)
    upload_id = request.headers.get("x-upload-id", "").strip()
    if upload_id:
        db.kv_delete(f"upres:{upload_id}")
    db.log_audit(
        "file.upload",
        actor="admin",
        target=filename,
        details={"size": manifest.total_size, "id": obj_id},
    )
    base = settings.base_url.rstrip("/")
    return JSONResponse(
        {
            "id": obj_id,
            "url": f"{base}/f/{obj_id}",
            "size": manifest.total_size,
            "sha256": sha_hex,
            "chunks": len(manifest.chunks),
        }
    )


async def _store_stream(
    request: Request,
    stream,
    filename: str,
    content_type: str | None = None,
    upload_id: str | None = None,
    resume_from: int = 0,
) -> tuple[Manifest, str]:
    """Drive the chunker over `stream`; return (manifest, sha256).

    With `upload_id` set, every stored chunk bumps the kv checkpoint
    `upres:<upload_id>` so a dropped connection can resume past stored
    chunks (they are drained, not re-posted). Checkpoints expire in 24h.
    """
    settings = request.app.state.settings
    backend = request.app.state.backend
    db = request.app.state.db
    manifest = Manifest(chunks=[], total_size=0)
    ck_key = f"upres:{upload_id}" if upload_id else None
    prior: list[dict] = []
    if ck_key and resume_from:
        try:
            raw = json.loads(db.kv_get(ck_key, "") or "")  # v0.15.20: envelope
            prior = raw.get("chunks", []) if isinstance(raw, dict) else raw
        except (json.JSONDecodeError, AttributeError):
            prior = []
        if resume_from > len(prior):
            raise HTTPException(
                409,
                f"cannot resume from {resume_from}: only {len(prior)} "
                "chunks are checkpointed for this upload id",
            )
        # pre-seed the manifest with the already-stored chunks
        for i, c in enumerate(prior[:resume_from]):
            manifest.chunks.append(
                Chunk(index=i, size=c["s"], file_id=c["f"], message_id=c.get("m"))
            )
    skip_remaining = resume_from

    def _checkpoint() -> None:
        if ck_key:
            db.kv_set(
                ck_key,
                json.dumps(
                    {
                        # _ts lets kv_prune_prefix drop checkpoints abandoned
                        # mid-upload (older than 24h) without a schema change
                        "_ts": int(time.time()),
                        "chunks": [
                            {"s": c.size, "f": c.file_id, "m": c.message_id}
                            for c in manifest.chunks
                        ],
                    },
                    separators=(",", ":"),
                ),
            )

    harvester = getattr(request.app.state, "harvester", None)

    configured_sec = settings.hmac_secret.get_secret_value() if settings.hmac_secret else None
    active_secret = effective_hmac_secret(db, configured_sec)

    async def on_chunk(data: bytes, media: bool = False) -> str:
        nonlocal skip_remaining
        if skip_remaining > 0:
            skip_remaining -= 1  # duplicate of an already-stored chunk: drain
            return ""
        chunk_idx = len(manifest.chunks)
        caption = encode_chunk_caption(
            obj_id=upload_id or "",
            chunk_idx=chunk_idx,
            total_chunks=0,
            filename=filename,
            total_size=0,
            content_type=content_type,
            secret=active_secret,
        )
        ref = await backend.store(
            data,
            opaque_chunk_name(chunk_idx),
            content_type=None,
            caption=caption,
        )
        bot_fid = None
        if harvester and ref.message_id is not None:
            try:
                bot_fid = await harvester.get_file_id_for_message(ref.message_id, timeout=2.0)
            except Exception as e:
                log.debug("harvester error for msg %s: %s", ref.message_id, e)

        manifest.chunks.append(
            Chunk(
                index=len(manifest.chunks),
                size=len(data),
                file_id=ref.file_id,
                message_id=ref.message_id,
                bot_file_id=bot_fid,
            )
        )
        _checkpoint()
        return ref.file_id

    try:
        _, sha_hex = await chunk_stream(
            stream,
            settings.chunk_size,
            on_chunk,
            is_first_chunk_media=bool(content_type),
        )
    except BodyReadTimeout as e:
        for c in manifest.chunks:  # best-effort rollback of posted blobs
            try:
                await backend.delete(
                    ObjectRef(file_id=c.file_id, message_id=c.message_id, backend=backend.name)
                )
            except Exception:  # noqa: BLE001
                pass
        log.warning("upload aborted: %s (%d chunks rolled back)", e, len(manifest.chunks))
        raise HTTPException(408, f"client stalled: {e}") from e
    except Exception as e:
        log.exception("upload chunk failed with error: %s", e)
        for c in manifest.chunks:  # best-effort rollback of posted blobs
            try:
                await backend.delete(
                    ObjectRef(file_id=c.file_id, message_id=c.message_id, backend=backend.name)
                )
            except Exception:  # noqa: BLE001
                pass
        if isinstance(e, FloodBudgetExceeded):
            raise HTTPException(504, f"telegram: {e.message}") from e
        if isinstance(e, TelegramError):
            raise HTTPException(502, f"telegram: {e.message}") from e
        raise HTTPException(502, f"storage error: {e}") from e
    return manifest, sha_hex


@router.post("/upload")
async def upload_multipart(request: Request, file: Annotated[UploadFile, File(...)]):
    """Multipart upload (field `file`). Streams to the backend in chunks.

    Resume (v0.15.20): send `X-Upload-Id` (any client-generated id) to make
    an upload resumable — same contract as `upload/raw`. If the connection
    drops, re-send with the same id + `X-Resume-From: <chunks-done>`;
    already-stored chunks are drained, not re-posted. Checkpoints live in
    kv for 24h.
    """
    require_uploader(request)
    limit_upload(request.app.state.db, request, _rate_upload(request))
    filename = file.filename or "upload.bin"
    content_type = file.content_type or "application/octet-stream"
    if (await _peek_size(file)) > _max_upload_bytes(request):
        raise HTTPException(413, "object exceeds configured ceiling")
    upload_id = request.headers.get("x-upload-id", "").strip() or None
    resume_from = 0
    if upload_id:
        try:
            resume_from = max(0, int(request.headers.get("x-resume-from", "0") or 0))
        except ValueError:
            raise HTTPException(400, "X-Resume-From must be an integer") from None
    manifest, sha_hex = await _store_stream(
        request,
        _UploadFileReader(file),
        filename,
        content_type=file.content_type,
        upload_id=upload_id,
        resume_from=resume_from,
    )
    return await _commit(request, manifest, sha_hex, filename, content_type)


@router.post("/upload/raw")
async def upload_raw(request: Request):
    """Raw byte-stream upload for very large files (no multipart framing).

    Filename via `X-File-Name` header (optional). Body is consumed as it
    arrives — never buffered whole.

    Resume (v0.8.6): send `X-Upload-Id` (any client-generated id) to make
    an upload resumable. If the connection drops, re-send with the same
    id + `X-Resume-From: <chunks-done>`; already-stored chunks are drained
    (not re-posted) and storage continues from chunk chunks-done+1. State
    lives in kv for 24h.
    """
    require_uploader(request)
    limit_upload(request.app.state.db, request, _rate_upload(request))
    filename = request.headers.get("x-file-name", "upload.bin")
    content_type = request.headers.get("content-type", "application/octet-stream")

    declared = int(request.headers.get("content-length", "0") or 0)
    if declared and declared > _max_upload_bytes(request):
        raise HTTPException(413, "object exceeds configured ceiling")

    upload_id = request.headers.get("x-upload-id", "").strip() or None
    resume_from = 0
    if upload_id:
        try:
            resume_from = max(0, int(request.headers.get("x-resume-from", "0") or 0))
        except ValueError:
            raise HTTPException(400, "X-Resume-From must be an integer") from None

    manifest, sha_hex = await _store_stream(
        request,
        _RequestBodyReader(request, request.app.state.settings.body_idle_timeout_s),
        filename,
        content_type=content_type,
        upload_id=upload_id,
        resume_from=resume_from,
    )
    return await _commit(request, manifest, sha_hex, filename, content_type)


async def _peek_size(file: UploadFile) -> int:
    """Return the declared size if known, else -1 (unknown → skip the check)."""
    size = getattr(file, "size", None)
    return size if isinstance(size, int) and size >= 0 else -1


class _UploadFileReader:
    """Adapts an UploadFile to the async `.read(n)` interface the chunker wants."""

    def __init__(self, file: UploadFile):
        self._f = file

    async def read(self, n: int) -> bytes:
        return await self._f.read(n)


class _RequestBodyReader:
    """Adapts the raw request body (server-side streaming) to `.read(n)`.

    Pulls from `request.stream()` only as much as the chunker asks — memory
    stays bounded by chunk size, not file size.

    An **idle timeout** (`body_idle_timeout_s`, v0.8.4) bounds each read:
    if the client stalls mid-body (crashed sender, broken pipe, or — as in
    the 500 MB bench bug — a client that declared more Content-Length than
    it actually sends), the request is aborted with 408 instead of hanging
    forever with no log trail.
    """

    def __init__(self, request: Request, idle_timeout_s: float = 300.0):
        self._iter = request.stream().__aiter__()
        self._buf = b""
        self._eof = False
        self._timeout = idle_timeout_s

    async def read(self, n: int) -> bytes:
        while len(self._buf) < n and not self._eof:
            try:
                self._buf += await asyncio.wait_for(self._iter.__anext__(), timeout=self._timeout)
            except StopAsyncIteration:
                self._eof = True
            except TimeoutError as e:
                raise BodyReadTimeout(
                    f"client stalled mid-body: no bytes for {self._timeout:.0f}s"
                ) from e
        out, self._buf = self._buf[:n], self._buf[n:]
        return out
