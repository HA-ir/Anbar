"""Download endpoints (F3). Streaming, chunk-aware, Range-capable.

The object layer hands out (chunk_index, offset, length) segments for a
byte range; we fetch each chunk from the backend on demand and stream the
requested slice. Memory stays bounded by one chunk, never the object.

Auth (F4): download links carry a `sig` HMAC — not implemented yet, so the
route currently serves any known object id. F4 swaps in the signed-URL
check via middleware without touching this file's streaming logic.
"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..objects import Manifest
from ..storage import ObjectRef

router = APIRouter()

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def _parse_range(header: str | None, total: int) -> tuple[int | None, int | None]:
    """Return (start, end) inclusive, or (None, None) for a full-range request."""
    if not header:
        return None, None
    m = _RANGE_RE.match(header.strip())
    if not m:
        raise _range_416(total)
    a, b = m.group(1), m.group(2)
    if not a and not b:
        raise _range_416(total)
    if not a:  # suffix range: last N bytes
        n = int(b)
        if n == 0:
            raise _range_416(total)
        return max(total - n, 0), total - 1
    start = int(a)
    end = int(b) if b else total - 1
    if start >= total or start > end:
        raise _range_416(total)
    return start, min(end, total - 1)


def _range_416(total: int) -> HTTPException:
    return HTTPException(416, "unsatisfiable range", headers={"Content-Range": f"bytes */{total}"})


@router.get("/{obj_id}")
async def download(request: Request, obj_id: str):
    db = request.app.state.db
    backend = request.app.state.backend
    row = db.get_object(obj_id)
    if row is None:
        raise HTTPException(404, "object not found")

    manifest = Manifest.from_json(row["manifest"])
    total = manifest.total_size
    start, end = _parse_range(request.headers.get("range"), total)
    if start is not None:
        assert end is not None
        length = end - start + 1
        segments = manifest.map_range(start, end + 1)  # [start, end) exclusive
    else:
        length = total
        segments = manifest.map_range(0, total)

    async def stream():
        fetched: dict[int, bytes] = {}  # chunk_index -> bytes (this request only)
        for idx, off, n in segments:
            chunk = fetched.get(idx)
            if chunk is None:
                ref = ObjectRef(file_id=manifest.chunks[idx].file_id, backend=backend.name)
                chunk = await backend.open(ref)
                fetched[idx] = chunk
            yield chunk[off : off + n]

    headers = {
        "Content-Length": str(length),
        "Content-Type": row["content_type"] or "application/octet-stream",
        "Content-Disposition": f'attachment; filename="{row["filename"]}"',
        "Accept-Ranges": "bytes",
    }
    if start is not None:
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"
    status = 206 if start is not None else 200
    return StreamingResponse(stream(), status_code=status, headers=headers)


@router.get("/{obj_id}/info")
async def info(request: Request, obj_id: str):
    db = request.app.state.db
    row = db.get_object(obj_id)
    if row is None:
        raise HTTPException(404, "object not found")
    manifest = json.loads(row["manifest"]) if row["manifest"] else {"chunks": []}
    return JSONResponse(
        {
            "id": row["id"],
            "filename": row["filename"],
            "size": row["size"],
            "sha256": row["sha256"],
            "content_type": row["content_type"],
            "chunks": len(manifest.get("chunks", [])),
            "created_at": row["created_at"],
            "downloaded": row["downloaded"],
        }
    )