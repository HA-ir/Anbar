"""Download endpoints (F3/F4). Streaming, chunk-aware, Range-capable, signed.

The object layer hands out (chunk_index, offset, length) segments for a
byte range; we fetch each chunk from the backend on demand and stream the
requested slice. Memory stays bounded by one chunk, never the object.

Auth (F4):
  - auth OFF  → everything open (public mode)
  - auth ON   → download requires a bearer key (admin/uploader) OR a valid
                `?sig=...&exp=...` signed link (403 invalid, 410 expired)
  - DELETE    → owner (the bearer key that uploaded it) or admin
  - /f/{id}/link → mint a signed link (bearer key required)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .. import runtime
from ..auth import (
    effective_auth_enabled,
    effective_hmac_secret,
    sign,
    verify_sig,
    whoami,
)
from ..objects import Manifest
from ..ratelimit import limit_download
from ..storage import ObjectRef

router = APIRouter()

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
DEFAULT_LINK_TTL = 3600  # seconds


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


def _authenticate_download(request: Request, obj_id: str) -> None:
    """Enforce the download auth matrix for this object (no-op when auth OFF)."""
    settings = request.app.state.settings
    db = request.app.state.db
    if not effective_auth_enabled(db, settings.auth_enabled):
        return
    role = whoami(request)
    if role in ("admin", "uploader"):
        return
    sig = request.query_params.get("sig")
    exp_raw = request.query_params.get("exp")
    if not sig or not exp_raw:
        raise HTTPException(401, "signed link or bearer key required")
    try:
        exp = int(exp_raw)
    except ValueError:
        raise HTTPException(403, "invalid signature") from None
    configured = settings.hmac_secret.get_secret_value() if settings.hmac_secret else None
    secret = effective_hmac_secret(db, configured)
    if not secret or not verify_sig(obj_id, exp, sig, secret):
        raise HTTPException(403, "invalid signature")
    if exp <= int(time.time()):
        raise HTTPException(410, "link expired")
    # optional per-object password (v0.9): kv holds an HMAC tag, the link
    # must carry ?pw=<plaintext> whose tag matches. Admin/uploader bypass.
    pw_tag = db.kv_get(f"pw:{obj_id}")
    if pw_tag:
        given = request.query_params.get("pw", "")
        configured2 = settings.hmac_secret.get_secret_value() if settings.hmac_secret else None
        secret2 = effective_hmac_secret(db, configured2) or ""
        want = hmac.new(secret2.encode(), f"pw:{obj_id}:{given}".encode(),
                        hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(want, pw_tag):
            raise HTTPException(403, "password required",
                                headers={"WWW-Authenticate": 'xBasic realm="anbar-pw"'})


@router.get("/{obj_id}")
async def download(request: Request, obj_id: str):
    settings = request.app.state.settings
    db = request.app.state.db
    backend = request.app.state.backend
    # rate limit before auth: an anonymous hammerer gets 429, not endless 401s
    limit_download(db, request, obj_id,
                   runtime.get_int(db, "rate_download", settings.rate_download_per_min))
    row = db.get_object(obj_id)
    if row is None:
        raise HTTPException(404, "object not found")
    _authenticate_download(request, obj_id)

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

    headers = {
        "Content-Length": str(length),
        "Content-Type": row["content_type"] or "application/octet-stream",
        "Content-Disposition": f'attachment; filename="{row["filename"]}"',
        "Accept-Ranges": "bytes",
    }
    if start is not None:
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"
    status = 206 if start is not None else 200
    db.bump_downloads(obj_id)

    cache = getattr(request.app.state, "cache", None)
    use_cache = (
        cache is not None
        and start is None  # full downloads only; ranges stay on the backend path
        and total > 0
        and total <= runtime.get_int(db, "cache_mb", settings.cache_max_mb) * 1024 * 1024
    )

    if use_cache and (path := cache.get(obj_id)) is not None:
        # cache hit: stream the temp file, zero backend calls
        async def cached_stream():
            with open(path, "rb") as f:
                while chunk := f.read(1024 * 1024):
                    yield chunk

        return StreamingResponse(cached_stream(), status_code=status, headers=headers)

    if use_cache:
        # cache miss: stream from the backend AND fill a temp file; commit to
        # the cache only if the stream completes (client abort drops the file).
        # Each chunk index appears in at most one segment (map_range walks
        # contiguously), so per-request memory is one chunk, never the object.
        async def filling_stream():
            tmp = cache.new_entry_path()
            size = 0
            try:
                with open(tmp, "wb") as out:
                    for idx, off, n in segments:
                        ref = ObjectRef(file_id=manifest.chunks[idx].file_id,
                                        backend=backend.name)
                        chunk = await backend.open(ref)
                        part = chunk[off : off + n]
                        out.write(part)
                        size += len(part)
                        yield part
                if size == total:
                    cache.add(obj_id, tmp, size)
            except BaseException:  # client abort (GeneratorExit) or backend error
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise

        return StreamingResponse(filling_stream(), status_code=status, headers=headers)

    async def stream():
        # one chunk in flight per request — never the whole object
        for idx, off, n in segments:
            ref = ObjectRef(file_id=manifest.chunks[idx].file_id, backend=backend.name)
            chunk = await backend.open(ref)
            yield chunk[off : off + n]

    return StreamingResponse(stream(), status_code=status, headers=headers)


@router.post("/{obj_id}/link")
async def mint_link(request: Request, obj_id: str, ttl: int = DEFAULT_LINK_TTL,
                    password: str = ""):
    """Mint a signed download link: `{base_url}/f/{id}?sig=...&exp=...`.

    `ttl` is the validity window in seconds (default 1 h, capped at 7 d).
    `password` (optional): the link then requires `?pw=<password>` too —
    stored as an HMAC tag, never in plaintext. Requires a bearer key.
    """
    settings = request.app.state.settings
    db = request.app.state.db
    row = db.get_object(obj_id)
    if row is None:
        raise HTTPException(404, "object not found")
    role = whoami(request)
    if effective_auth_enabled(db, settings.auth_enabled) and role == "anon":
        raise HTTPException(401, "authentication required")
    configured = settings.hmac_secret.get_secret_value() if settings.hmac_secret else None
    secret = effective_hmac_secret(db, configured)
    if not secret:
        raise HTTPException(500, "hmac secret not configured")
    ttl = max(60, min(ttl, 7 * 86400))
    exp = int(time.time()) + ttl
    sig = sign(obj_id, exp, secret)
    base = settings.base_url.rstrip("/")
    url = f"{base}/f/{obj_id}?sig={sig}&exp={exp}"
    out: dict = {"url": url, "expires_at": exp, "ttl_seconds": ttl}
    if password.strip():
        pw_tag = hmac.new(secret.encode(), f"pw:{obj_id}:{password.strip()}".encode(),
                          hashlib.sha256).hexdigest()[:32]
        db.kv_set(f"pw:{obj_id}", pw_tag)
        out["password_protected"] = True
        # append pw only as a hint param — real check happens server-side;
        # we do NOT put the password itself in the URL.
    return out


@router.get("/{obj_id}/qr")
async def qr(request: Request, obj_id: str):
    """SVG QR code of the signed share link (admin/uploader)."""
    from fastapi.responses import Response

    from ..qrcode import qr_svg

    settings = request.app.state.settings
    row = request.app.state.db.get_object(obj_id)
    if row is None:
        raise HTTPException(404, "object not found")
    role = whoami(request)
    if effective_auth_enabled(request.app.state.db,
                              settings.auth_enabled) and role == "anon":
        raise HTTPException(401, "authentication required")
    configured = settings.hmac_secret.get_secret_value() if settings.hmac_secret else None
    secret = effective_hmac_secret(request.app.state.db, configured)
    if not secret:
        raise HTTPException(500, "hmac secret not configured")
    ttl = 7 * 86400
    exp = int(time.time()) + ttl
    sig = sign(obj_id, exp, secret)
    url = f"{settings.base_url.rstrip('/')}/f/{obj_id}?sig={sig}&exp={exp}"
    return Response(content=qr_svg(url), media_type="image/svg+xml",
                    headers={"Cache-Control": "no-store"})


@router.delete("/{obj_id}")
async def delete(request: Request, obj_id: str):
    """Delete the object (metadata + channel blobs). Owner or admin only.

    The Telegram blobs are deleted best-effort; metadata removal is the
    authoritative step.
    """
    settings = request.app.state.settings
    db = request.app.state.db
    backend = request.app.state.backend
    row = db.get_object(obj_id)
    if row is None:
        raise HTTPException(404, "object not found")
    role = whoami(request)
    if effective_auth_enabled(db, settings.auth_enabled) and role == "anon":
        raise HTTPException(401, "authentication required")
    is_owner = bool(row["uploader_key"]) and _key_matches(request, row["uploader_key"])
    if not (role == "admin" or (role == "uploader" and is_owner)):
        raise HTTPException(403, "admin or owner key required")

    manifest = json.loads(row["manifest"]) if row["manifest"] else {"chunks": []}
    deleted_blobs = 0
    for c in manifest.get("chunks", []):
        try:
            ref = ObjectRef(
                file_id=c["f"],
                message_id=c.get("m"),
                backend=row["backend"],
            )
            if await backend.delete(ref):
                deleted_blobs += 1
        except Exception:  # noqa: BLE001 - best-effort remote cleanup
            pass
    db.delete_object(obj_id)
    # drop any cached copy of this object (and its chunks, if chunked ids share
    # the prefix) so a re-upload under a new id never serves stale bytes
    cache = getattr(request.app.state, "cache", None)
    if cache is not None:
        cache.remove(obj_id)
    db.kv_delete(f"pw:{obj_id}")  # drop a stale pw tag, if any
    return {"deleted": True, "id": obj_id, "blobs_removed": deleted_blobs}


@router.patch("/{obj_id}")
async def rename(request: Request, obj_id: str):
    """Rename an object (metadata only; blobs untouched). Admin/owner only."""
    db = request.app.state.db
    settings = request.app.state.settings
    row = db.get_object(obj_id)
    if row is None:
        raise HTTPException(404, "object not found")
    role = whoami(request)
    if effective_auth_enabled(db, settings.auth_enabled) and role == "anon":
        raise HTTPException(401, "authentication required")
    is_owner = bool(row["uploader_key"]) and _key_matches(request, row["uploader_key"])
    if not (role == "admin" or (role == "uploader" and is_owner)):
        raise HTTPException(403, "admin or owner key required")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "expected JSON {filename}") from None
    name = ((body or {}).get("filename") or "").strip()
    if not name or len(name) > 200 or "/" in name or "\\" in name:
        raise HTTPException(400, "invalid filename")
    if not db.rename_object(obj_id, name):
        raise HTTPException(404, "object not found")
    return {"renamed": True, "id": obj_id, "filename": name}


def _key_matches(request: Request, uploader_key: str) -> bool:
    """Compare the caller's bearer key against the stored uploader key."""
    auth = request.headers.get("authorization", "")
    key = auth[7:] if auth.lower().startswith("bearer ") else None
    if not key:
        return False
    from ..auth import constant_time_equal

    return constant_time_equal(key, uploader_key)


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