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

from ..auth import effective_auth_enabled, whoami
from ..db import Database
from ..objects import Chunk, Manifest, chunk_stream, new_object_id, opaque_chunk_name
from ..storage import ObjectRef

router = APIRouter(prefix="/s3")


def _xml_error(code: str, message: str, resource: str, status_code: int = 400) -> Response:
    root = ET.Element("Error")
    ET.SubElement(root, "Code").text = code
    ET.SubElement(root, "Message").text = message
    ET.SubElement(root, "Resource").text = resource
    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return Response(content=xml_bytes, status_code=status_code, media_type="application/xml")


def _check_s3_auth(request: Request):
    settings = request.app.state.settings
    db = request.app.state.db
    if effective_auth_enabled(db, settings.auth_enabled):
        role = whoami(request)
        if role == "anon":
            raise HTTPException(401, "S3 Access Denied")


@router.get("/{bucket}")
async def list_objects_v2(bucket: str, request: Request):
    """List objects in a bucket (stored as prefix 'bucket/')."""
    _check_s3_auth(request)
    db: Database = request.app.state.db
    prefix = f"{bucket}/"
    rows = db.list_objects(limit=1000)
    matching = [r for r in rows if r["filename"].startswith(prefix) or bucket == "default"]

    root = ET.Element("ListBucketResult", attrib={"xmlns": "http://s3.amazonaws.com/doc/2006-03-01/"})
    ET.SubElement(root, "Name").text = bucket
    ET.SubElement(root, "KeyCount").text = str(len(matching))
    ET.SubElement(root, "MaxKeys").text = "1000"
    ET.SubElement(root, "IsTruncated").text = "false"

    for r in matching:
        full_row = db.get_object(r["id"]) or r
        contents = ET.SubElement(root, "Contents")
        is_pfx = r["filename"].startswith(prefix)
        key_name = r["filename"][len(prefix) :] if is_pfx else r["filename"]
        ET.SubElement(contents, "Key").text = key_name
        ET.SubElement(contents, "Size").text = str(r["size"])
        ET.SubElement(contents, "ETag").text = f'"{full_row.get("sha256") or ""}"'
        ET.SubElement(contents, "LastModified").text = formatdate(r["created_at"], usegmt=True)

    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return Response(content=xml_bytes, media_type="application/xml")


@router.put("/{bucket}/{key:path}")
async def put_object(bucket: str, key: str, request: Request):
    """PutObject into Telegram backend via standard chunking."""
    _check_s3_auth(request)
    backend = request.app.state.backend
    settings = request.app.state.settings
    db: Database = request.app.state.db

    full_filename = f"{bucket}/{key}" if bucket != "default" else key
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
        return ref.file_id

    from .upload import _RequestBodyReader

    # Read body stream
    body_reader = _RequestBodyReader(request, request.app.state.settings.body_idle_timeout_s)
    total_size, sha256_hex = await chunk_stream(
        body_reader,
        settings.chunk_size,
        on_chunk,
    )
    manifest.total_size = total_size
    obj_id = new_object_id()

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
        for idx, off, n in segments:
            c = manifest.chunks[idx]
            ref = ObjectRef(file_id=c.file_id, message_id=c.message_id, backend=backend.name)
            chunk_data = await backend.open(ref)
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
    _check_s3_auth(request)
    db: Database = request.app.state.db
    backend = request.app.state.backend
    obj_id = db.kv_get(f"s3:{bucket}:{key}")
    if not obj_id:
        return Response(status_code=204)

    row = db.get_object(obj_id)
    if row:
        manifest = Manifest.from_json(row["manifest"])
        for c in manifest.chunks:
            try:
                ref = ObjectRef(file_id=c.file_id, message_id=c.message_id, backend=backend.name)
                await backend.delete(ref)
            except Exception:
                pass
        db.delete_object(obj_id)
    db.kv_delete(f"s3:{bucket}:{key}")
    return Response(status_code=204)
