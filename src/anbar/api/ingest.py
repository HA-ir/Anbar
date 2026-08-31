"""URL ingest (v0.8.5): server-side download from a remote URL straight to
the Telegram-backed storage — no local disk.

`POST /api/v1/upload/url  {"url": ..., "filename": ...}`

The remote body is streamed through the same chunker used for direct
uploads, so memory stays bounded by chunk size. The job runs in the
background; the UI polls `GET /api/v1/upload/url/{job_id}` for progress
(bytes pulled, chunk count) and the finished object payload.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request

from ..auth import require_admin
from ..objects import (  # noqa: F401 (Chunk re-used in _run_job)
    Chunk,
    Manifest,
    new_object_id,
    opaque_chunk_name,
)
from ..storage.base import ObjectRef

router = APIRouter()
log = logging.getLogger("anbar.ingest")

# module-level job table (single-process service; survives per-request)
JOBS: dict[str, dict] = {}
JOBS_MAX_AGE_S = 3600  # finished jobs are pruned after 1h (v0.15.20, ARCH-03)


def _prune_jobs() -> int:
    """Drop finished ingest jobs older than JOBS_MAX_AGE_S (bounded memory).

    Called from the job status endpoint (cheap, piggybacks on traffic).
    Returns rows removed.
    """
    now = time.time()
    stale = [
        jid
        for jid, j in JOBS.items()
        if j.get("state") in ("done", "error") and now - j.get("started", now) > JOBS_MAX_AGE_S
    ]
    for jid in stale:
        JOBS.pop(jid, None)
    return len(stale)
MAX_CONCURRENT = 2
_SEM = asyncio.Semaphore(MAX_CONCURRENT)

# streaming knobs
CONNECT_TIMEOUT = 15.0
IDLE_TIMEOUT = 60.0  # no bytes from origin for this long → abort
MAX_REDIRECTS = 5


class _UrlReader:
    """Adapts an httpx streaming response to `.read(n)` with an idle cap."""

    def __init__(self, resp, idle_timeout_s: float):
        self._aiter = resp.aiter_bytes(256 * 1024).__aiter__()
        self._buf = b""
        self._eof = False
        self._timeout = idle_timeout_s

    async def read(self, n: int) -> bytes:
        while len(self._buf) < n and not self._eof:
            piece = b""
            try:
                piece = await asyncio.wait_for(self._aiter.__anext__(), timeout=self._timeout)
            except StopAsyncIteration:
                self._eof = True
            except TimeoutError as e:
                raise RuntimeError(f"origin stalled: no bytes for {self._timeout:.0f}s") from e
            if piece:
                self._buf += piece
        out, self._buf = self._buf[:n], self._buf[n:]
        return out


def _filename_from_url(url: str, headers: httpx.Headers | None) -> str:
    # 1) Content-Disposition attachment filename
    if headers:
        cd = headers.get("content-disposition", "")
        if "filename=" in cd:
            raw = cd.split("filename=", 1)[1].strip().strip('"').split(";", 1)[0]
            if raw.strip():
                return unquote(raw)[:200]
    # 2) last path segment
    path = urlsplit(url).path
    seg = unquote(PurePosixPath(path).name or "").strip()
    return (seg or "ingest.bin")[:200]


def _guess_content_type(headers: httpx.Headers | None, fallback: str) -> str:
    if headers:
        ct = headers.get("content-type", "").split(";")[0].strip()
        if ct and ct != "application/octet-stream":
            return ct
    return fallback


async def _run_job(app, job_id: str, url: str, filename: str | None) -> None:
    job = JOBS[job_id]
    settings = app.state.settings
    async with _SEM:
        try:
            timeout = httpx.Timeout(settings.ingest_read_timeout_s, connect=CONNECT_TIMEOUT)
            async with httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=MAX_REDIRECTS,
                timeout=timeout,
                headers={"user-agent": "anbar-ingest/0.8"},
            ) as client:
                async with client.stream("GET", url) as resp:
                    if resp.status_code >= 400:
                        raise RuntimeError(f"origin returned HTTP {resp.status_code}")
                    fname = filename or _filename_from_url(url, resp.headers)
                    ctype = _guess_content_type(resp.headers, "application/octet-stream")
                    decl = int(resp.headers.get("content-length", "0") or 0)
                    if decl and decl > settings.max_upload_mb * 1024 * 1024:
                        raise RuntimeError("remote file exceeds configured ceiling")
                    job["total"] = decl  # 0 = unknown → indeterminate progress

                    reader = _UrlReader(resp, IDLE_TIMEOUT)
                    total_in = 0

                    async def on_chunk(data: bytes) -> ObjectRef:
                        nonlocal total_in
                        total_in += len(data)
                        job["bytes"] = total_in
                        job["chunks"] += 1
                        return await app.state.backend.store(data, opaque_chunk_name(job["chunks"]))

                    manifest = Manifest(chunks=[], total_size=0)

                    # reuse the upload chunker via a tiny shim that mirrors
                    # _store_stream's rollback semantics
                    from ..objects import chunk_stream

                    async def put(data: bytes, media: bool = False) -> None:
                        ref = await on_chunk(data)
                        manifest.chunks.append(
                            Chunk(
                                index=len(manifest.chunks),
                                size=len(data),
                                file_id=ref.file_id,
                                message_id=ref.message_id,
                            )
                        )

                    try:
                        _, sha = await chunk_stream(reader, settings.chunk_size, put)
                    except BaseException:
                        for c in manifest.chunks:  # best-effort rollback
                            try:
                                await app.state.backend.delete(
                                    ObjectRef(
                                        file_id=c.file_id,
                                        message_id=c.message_id,
                                        backend=app.state.backend.name,
                                    )
                                )
                            except Exception:  # noqa: BLE001
                                pass
                        raise
                    manifest.total_size = sum(c.size for c in manifest.chunks)

                    # commit into the DB exactly like a normal upload
                    obj_id = new_object_id()
                    db = app.state.db
                    db.insert_object(
                        {
                            "id": obj_id,
                            "file_id": manifest.chunks[0].file_id,
                            "backend": app.state.backend.name,
                            "filename": fname,
                            "size": manifest.total_size,
                            "content_type": ctype,
                            "sha256": sha,
                            "manifest": manifest.to_json(),
                            "uploader_key": job.get("key"),
                        }
                    )
                    job["object"] = {
                        "id": obj_id,
                        "url": f"/f/{obj_id}",
                        "filename": fname,
                        "size": manifest.total_size,
                        "chunks": len(manifest.chunks),
                        "sha256": sha,
                    }
                    job["state"] = "done"
                    # best-effort channel notification (never blocks the job)
                    import time as _t

                    from .notify import notify_ingest_done

                    try:
                        await asyncio.wait_for(
                            notify_ingest_done(
                                app.state.backend,
                                settings.base_url,
                                job["object"],
                                url,
                                _t.time() - job["started"],
                            ),
                            timeout=10,
                        )
                    except Exception:  # noqa: BLE001
                        pass
        except Exception as e:  # noqa: BLE001
            log.warning("ingest %s failed: %s", job_id, e)
            job["state"] = "error"
            job["error"] = str(e)


@router.post("/upload/url")
async def upload_url(request: Request):
    require_admin(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "expected JSON {url, filename?}") from None
    url = (body or {}).get("url", "").strip()
    filename = ((body or {}).get("filename") or "").strip() or None
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "url must be http(s)")
    if len(url) > 2048:
        raise HTTPException(400, "url too long")

    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {
        "state": "pulling",
        "bytes": 0,
        "chunks": 0,
        "total": 0,
        "started": time.time(),
        "key": None,
        "object": None,
        "error": None,
    }
    asyncio.get_running_loop().create_task(_run_job(request.app, job_id, url, filename))
    return {"job_id": job_id}


@router.get("/upload/url/{job_id}")
async def upload_url_status(request: Request, job_id: str):
    require_admin(request)
    _prune_jobs()
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    out = {k: v for k, v in job.items() if k != "key"}
    out["elapsed"] = round(time.time() - job["started"], 1)
    return out
