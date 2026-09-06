"""v0.11: S3-compatible REST API endpoints (/s3/{bucket}/{key:path}).
Supports:
- PUT /s3/{bucket}/{key} (PutObject)
- GET /s3/{bucket}/{key} (GetObject with Range & ETag)
- HEAD /s3/{bucket}/{key} (HeadObject)
- DELETE /s3/{bucket}/{key} (DeleteObject)
- GET /s3/{bucket} (ListObjectsV2)
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import formatdate

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from .. import runtime
from ..auth import effective_auth_enabled, whoami
from ..db import Database
from ..object_service import purge_object_blobs as _purge_object_blobs
from ..objects import (
    Chunk,
    Manifest,
    UploadCeilingExceeded,
    chunk_stream,
    new_object_id,
    opaque_chunk_name,
)
from ..ratelimit import limit_download, limit_upload
from ..storage import ObjectRef

router = APIRouter(prefix="/s3")


def _xml_error(code: str, message: str, resource: str, status_code: int = 400) -> Response:
    root = ET.Element("Error")
    ET.SubElement(root, "Code").text = code
    ET.SubElement(root, "Message").text = message
    ET.SubElement(root, "Resource").text = resource
    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return Response(content=xml_bytes, status_code=status_code, media_type="application/xml")


def _check_s3_auth(request: Request, write: bool = False):
    settings = request.app.state.settings
    db = request.app.state.db
    auth_enabled = effective_auth_enabled(db, settings.auth_enabled)
    role = whoami(request)
    if auth_enabled:
        if role == "anon":
            raise HTTPException(401, "S3 Access Denied")
    elif write and role == "anon":
        # SEC-B3: Even when general auth is OFF, anonymous S3 writes are rejected
        raise HTTPException(401, "S3 writes require authentication")


@router.get("/{bucket}")
async def list_objects_v2(
    bucket: str,
    request: Request,
    max_keys: int = 1000,
    continuation_token: str | None = None,
):
    """List objects in a bucket (stored as prefix 'bucket/')."""
    _check_s3_auth(request)
    db: Database = request.app.state.db
    settings = request.app.state.settings
    rate = runtime.get_int(db, "rate_download", settings.rate_download_per_min)
    limit_download(db, request, f"s3:{bucket}", rate)
    prefix = f"{bucket}/"
    # SEC-B3: never fall back to global default-bucket enumeration. S3 lists
    rows = db.list_objects_by_prefix(prefix)
    matching = [r for r in rows if r["filename"].startswith(prefix) and not r.get("deleted_at")]

    max_keys_int = max(1, min(int(request.query_params.get("max-keys", max_keys)), 1000))
    offset = 0
    token = request.query_params.get("continuation-token") or continuation_token
    if token:
        try:
            offset = max(0, int(token))
        except ValueError:
            offset = 0

    paged = matching[offset : offset + max_keys_int]
    is_truncated = (offset + max_keys_int) < len(matching)
    next_token = str(offset + max_keys_int) if is_truncated else None

    root = ET.Element(
        "ListBucketResult", attrib={"xmlns": "http://s3.amazonaws.com/doc/2006-03-01/"}
    )
    ET.SubElement(root, "Name").text = bucket
    ET.SubElement(root, "KeyCount").text = str(len(paged))
    ET.SubElement(root, "MaxKeys").text = str(max_keys_int)
    ET.SubElement(root, "IsTruncated").text = "true" if is_truncated else "false"
    if next_token:
        ET.SubElement(root, "NextContinuationToken").text = next_token

    for r in paged:
        # REL-C4: sha256 is already selected in db.list_objects() — zero N+1 queries
        contents = ET.SubElement(root, "Contents")
        is_pfx = r["filename"].startswith(prefix)
        key_name = r["filename"][len(prefix) :] if is_pfx else r["filename"]
        ET.SubElement(contents, "Key").text = key_name
        ET.SubElement(contents, "Size").text = str(r["size"])
        ET.SubElement(contents, "ETag").text = f'"{r.get("sha256") or ""}"'
        ET.SubElement(contents, "LastModified").text = formatdate(r["created_at"], usegmt=True)

    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return Response(content=xml_bytes, media_type="application/xml")


@router.put("/{bucket}/{key:path}")
async def put_object(bucket: str, key: str, request: Request):
    """PutObject into Telegram backend via standard chunking."""
    _check_s3_auth(request, write=True)
    backend = request.app.state.backend
    settings = request.app.state.settings
    db: Database = request.app.state.db

    # SEC-B3: rate limit S3 uploads
    limit_upload(db, request, runtime.get_int(db, "rate_upload", settings.rate_upload_per_min))

    # SEC-B3 & SEC-B4: running upload size ceiling
    max_bytes = runtime.get_int(db, "max_upload_mb", settings.max_upload_mb) * 1024 * 1024
    declared = int(request.headers.get("content-length", "0") or 0)
    if declared and declared > max_bytes:
        raise HTTPException(413, "object exceeds configured ceiling")

    full_filename = f"{bucket}/{key}"
    content_type = request.headers.get("content-type") or "application/octet-stream"

    # Stream chunks
    manifest = Manifest()

    async def on_chunk(data: bytes, media: bool = False) -> str:
        ref = await backend.store(data, opaque_chunk_name(len(manifest.chunks)), content_type=None)
        manifest.chunks.append(
            Chunk(
                index=len(manifest.chunks),
                size=len(data),
                file_id=ref.file_id,
                message_id=ref.message_id,
            )
        )
        return str(ref.file_id)

    from .upload import _RequestBodyReader

    # Read body stream with running byte counter
    body_reader = _RequestBodyReader(request, request.app.state.settings.body_idle_timeout_s)
    try:
        total_size, sha256_hex = await chunk_stream(
            body_reader,
            settings.chunk_size,
            on_chunk,
            max_bytes=max_bytes,
        )
    except UploadCeilingExceeded as e:
        for c in manifest.chunks:
            try:
                await backend.delete(
                    ObjectRef(
                        file_id=c.file_id,
                        message_id=c.message_id,
                        backend=backend.name,
                    )
                )
            except Exception:
                pass
        raise HTTPException(413, str(e)) from e

    manifest.total_size = total_size
    obj_id = new_object_id()

    # SEC-B7: Reuse the canonical purge path so old blobs, metadata, tags and
    # subtitles cannot leak behind the replaced S3 key.
    old_obj_id = db.kv_get(f"s3:{bucket}:{key}")
    if old_obj_id:
        old_row = db.get_object(old_obj_id)
        if old_row:
            await _purge_object_blobs(
                backend,
                db,
                old_row,
                pool=getattr(request.app.state, "bot_pool", None),
            )
        db.kv_delete(f"s3:{bucket}:{key}")

    # Save to SQLite
    db.insert_object(
        {
            "id": obj_id,
            "file_id": manifest.chunks[0].file_id if manifest.chunks else "",
            "backend": backend.name,
            "filename": full_filename,
            "size": total_size,
            "content_type": content_type,
            "sha256": sha256_hex,
            "manifest": manifest.to_json(),
            "uploader_key": "s3",
        }
    )
    # Save S3 key mapping: s3:<bucket>:<key> -> obj_id
    db.kv_set(f"s3:{bucket}:{key}", obj_id)

    headers = {
        "ETag": f'"{sha256_hex}"',
        "x-amz-request-id": obj_id,
    }
    return Response(status_code=200, headers=headers)


@router.head("/{bucket}/{key:path}")
async def head_object(bucket: str, key: str, request: Request):
    """HeadObject metadata."""
    _check_s3_auth(request)
    db: Database = request.app.state.db
    settings = request.app.state.settings
    rate = runtime.get_int(db, "rate_download", settings.rate_download_per_min)
    limit_download(db, request, f"s3:{bucket}:{key}", rate)
    obj_id = db.kv_get(f"s3:{bucket}:{key}")
    if not obj_id:
        return Response(status_code=404)
    row = db.get_object(obj_id)
    if not row:
        return Response(status_code=404)

    headers = {
        "Content-Length": str(row["size"]),
        "Content-Type": row["content_type"] or "application/octet-stream",
        "ETag": f'"{row["sha256"]}"',
        "Accept-Ranges": "bytes",
        "Last-Modified": formatdate(row["created_at"], usegmt=True),
    }
    return Response(status_code=200, headers=headers)


@router.get("/{bucket}/{key:path}")
async def get_object(bucket: str, key: str, request: Request):
    """GetObject with Range and ETag support."""
    _check_s3_auth(request)
    db: Database = request.app.state.db
    settings = request.app.state.settings
    rate = runtime.get_int(db, "rate_download", settings.rate_download_per_min)
    limit_download(db, request, f"s3:{bucket}:{key}", rate)
    obj_id = db.kv_get(f"s3:{bucket}:{key}")
    if not obj_id:
        return _xml_error("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
    row = db.get_object(obj_id)
    if not row:
        return _xml_error("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)

    manifest = Manifest.from_json(row["manifest"])
    total = manifest.total_size
    backend = request.app.state.backend

    range_h = request.headers.get("range")
    if range_h and range_h.startswith("bytes="):
        # v0.15.13 audit fix: malformed/out-of-bounds Range previously raised an
        # unhandled ValueError => 500. Parse defensively and answer 416 per the
        # S3/HTTP spec, clamping an oversized suffix end to the last byte.
        raw = range_h[6:].strip()
        if "," in raw:  # multi-range: serve the full object (simplest spec-legal fallback)
            start, end = None, None
            length = total
            segments = manifest.map_range(0, total)
            status_code = 200
        else:
            parts = raw.split("-")
            try:
                start = int(parts[0]) if parts[0] else 0
                end = int(parts[1]) if parts[1] else total - 1
            except (ValueError, IndexError):
                return _xml_error(
                    "InvalidRange",
                    "The requested range is not satisfiable.",
                    f"/{bucket}/{key}",
                    416,
                )
            if start >= total or start > end:
                return _xml_error(
                    "InvalidRange",
                    "The requested range is not satisfiable.",
                    f"/{bucket}/{key}",
                    416,
                )
            end = min(end, total - 1)  # clamp oversized end (RFC 9110 §14.2)
            length = end - start + 1
            segments = manifest.map_range(start, end + 1)
            status_code = 206
    else:
        start, end = None, None
        length = total
        segments = manifest.map_range(0, total)
        status_code = 200

    etag = f'"{row["sha256"]}"'
    if_none_match = request.headers.get("if-none-match")
    if if_none_match and start is None and (if_none_match == etag or if_none_match == "*"):
        return Response(status_code=304, headers={"ETag": etag, "Accept-Ranges": "bytes"})

    async def stream_body():
        pool = getattr(request.app.state, "bot_pool", None)
        for idx, off, n in segments:
            c = manifest.chunks[idx]
            # ARCH-01: fetch from the holding member when it differs from the
            # object's primary backend
            chunk_backend = backend
            if c.backend and pool is not None:
                chunk_backend = pool.by_name(c.backend) or backend
            ref = ObjectRef(file_id=c.file_id, message_id=c.message_id, backend=chunk_backend.name)
            chunk_data = await chunk_backend.open(ref)
            yield chunk_data[off : off + n]

    headers = {
        "Content-Length": str(length),
        "Content-Type": row["content_type"] or "application/octet-stream",
        "ETag": etag,
        "Accept-Ranges": "bytes",
        "Last-Modified": formatdate(row["created_at"], usegmt=True),
    }
    if start is not None:
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"

    return StreamingResponse(stream_body(), status_code=status_code, headers=headers)


@router.delete("/{bucket}/{key:path}")
async def delete_object(bucket: str, key: str, request: Request):
    """DeleteObject from storage."""
    _check_s3_auth(request, write=True)
    db: Database = request.app.state.db
    backend = request.app.state.backend
    obj_id = db.kv_get(f"s3:{bucket}:{key}")
    if not obj_id:
        return Response(status_code=204)

    row = db.get_object(obj_id)
    if row:
        manifest = Manifest.from_json(row["manifest"])
        pool = getattr(request.app.state, "bot_pool", None)
        for c in manifest.chunks:
            # ARCH-01: delete from the holding member, not always the primary
            chunk_backend = backend
            if c.backend and pool is not None:
                chunk_backend = pool.by_name(c.backend) or backend
            try:
                ref = ObjectRef(
                    file_id=c.file_id, message_id=c.message_id, backend=chunk_backend.name
                )
                await chunk_backend.delete(ref)
            except Exception:
                pass
        db.delete_object(obj_id)
    db.kv_delete(f"s3:{bucket}:{key}")
    return Response(status_code=204)
