"""Upload endpoints (F2). Multipart + raw streaming, chunked, manifest-backed.

Auth is enforced by the middleware layer (F4); F2 records the uploader for
ownership (used by DELETE in F4).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from .. import runtime
from ..auth import require_uploader
from ..objects import Chunk, Manifest, chunk_stream, new_object_id
from ..ratelimit import limit_upload
from ..storage import FloodBudgetExceeded, ObjectRef, TelegramError

router = APIRouter()


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


async def _commit(request: Request, manifest: Manifest, sha_hex: str, filename: str,
                  content_type: str) -> JSONResponse:
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


async def _store_stream(request: Request, stream, filename: str) -> tuple[Manifest, str]:
    """Drive the chunker over `stream`; return (manifest, sha256)."""
    settings = request.app.state.settings
    backend = request.app.state.backend
    manifest = Manifest(chunks=[], total_size=0)

    async def on_chunk(data: bytes) -> str:
        ref = await backend.store(data, f"{filename}.part")
        manifest.chunks.append(
            Chunk(index=len(manifest.chunks), size=len(data), file_id=ref.file_id,
                  message_id=ref.message_id)
        )
        return ref.file_id

    try:
        _, sha_hex = await chunk_stream(stream, settings.chunk_size, on_chunk)
    except Exception as e:
        for c in manifest.chunks:  # best-effort rollback of posted blobs
            try:
                await backend.delete(
                    ObjectRef(file_id=c.file_id, message_id=c.message_id,
                              backend=backend.name)
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
    """Multipart upload (field `file`). Streams to the backend in chunks."""
    require_uploader(request)
    limit_upload(request.app.state.db, request, _rate_upload(request))
    filename = file.filename or "upload.bin"
    content_type = file.content_type or "application/octet-stream"
    if (await _peek_size(file)) > _max_upload_bytes(request):
        raise HTTPException(413, "object exceeds configured ceiling")
    manifest, sha_hex = await _store_stream(request, _UploadFileReader(file), filename)
    return await _commit(request, manifest, sha_hex, filename, content_type)


@router.post("/upload/raw")
async def upload_raw(request: Request):
    """Raw byte-stream upload for very large files (no multipart framing).

    Filename via `X-File-Name` header (optional). Body is consumed as it
    arrives — never buffered whole.
    """
    require_uploader(request)
    limit_upload(request.app.state.db, request, _rate_upload(request))
    filename = request.headers.get("x-file-name", "upload.bin")
    content_type = request.headers.get("content-type", "application/octet-stream")

    declared = int(request.headers.get("content-length", "0") or 0)
    if declared and declared > _max_upload_bytes(request):
        raise HTTPException(413, "object exceeds configured ceiling")

    manifest, sha_hex = await _store_stream(request, _RequestBodyReader(request), filename)
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
    """

    def __init__(self, request: Request):
        self._iter = request.stream().__aiter__()
        self._buf = b""
        self._eof = False

    async def read(self, n: int) -> bytes:
        while len(self._buf) < n and not self._eof:
            try:
                self._buf += await self._iter.__anext__()
            except StopAsyncIteration:
                self._eof = True
        out, self._buf = self._buf[:n], self._buf[n:]
        return out