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
from ..auth import require_uploader
from ..object_service import ObjectService, ResumeOutOfRange, describe_storage_error
from ..objects import Manifest
from ..ratelimit import limit_upload

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
    """Commit via ObjectService and build the JSON response.

    `svc` (when given) is the ObjectService that produced `manifest` — its
    checkpoint is dropped here; otherwise cleanup falls back to the header
    (compat with tests calling the pieces directly).
    """
    settings = request.app.state.settings
    db = request.app.state.db
    svc: ObjectService | None = getattr(manifest, "_svc", None)
    if svc is not None:
        obj_id = svc.commit(sha_hex=sha_hex, uploader_key=_uploader_key(request))
        svc.drop_checkpoint()
    else:
        svc = _service_for(request, filename, content_type, None, 0)
        svc.manifest = manifest
        obj_id = svc.commit(sha_hex=sha_hex, uploader_key=_uploader_key(request))
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
    """Store `stream` via the shared ObjectService; return (manifest, sha256).

    With `upload_id` set, every stored chunk bumps the kv checkpoint
    `upres:<upload_id>` so a dropped connection can resume past stored
    chunks (they are drained, not re-posted). Checkpoints expire in 24h.
    """
    svc = _service_for(request, filename, content_type, upload_id, resume_from)
    svc.harvester = getattr(request.app.state, "harvester", None)
    try:
        manifest, sha_hex = await svc.store_stream(stream)
    except ResumeOutOfRange as e:
        raise HTTPException(409, str(e)) from None
    except BodyReadTimeout as e:
        log.warning("upload aborted: %s (%d chunks rolled back)", e, len(svc.manifest.chunks))
        raise HTTPException(408, f"client stalled: {e}") from e
    except Exception as e:
        log.exception("upload chunk failed with error: %s", e)
        status, detail = describe_storage_error(e)
        raise HTTPException(status, detail) from e
    manifest._svc = svc  # noqa: SLF001 — commit drops the checkpoint via it
    return manifest, sha_hex


def _service_for(
    request: Request,
    filename: str,
    content_type: str | None,
    upload_id: str | None,
    resume_from: int,
) -> ObjectService:
    return ObjectService(
        backend=request.app.state.backend,
        db=request.app.state.db,
        settings=request.app.state.settings,
        filename=filename,
        content_type=content_type,
        upload_id=upload_id,
        resume_from=resume_from,
    )


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
