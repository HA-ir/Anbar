"""Admin endpoints (F4): status, auth toggle, secret rotation, object listing."""
from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..auth import (
    KV_AUTH,
    KV_HMAC_SECRET,
    effective_auth_enabled,
    new_secret,
    require_admin,
)

router = APIRouter()


@router.get("/admin/status")
async def status(request: Request):
    s = request.app.state.settings
    db = request.app.state.db
    backend = request.app.state.backend
    cache = getattr(request.app.state, "cache", None)
    return {
        "status": "ok",
        "backend": getattr(backend, "name", s.backend.value),
        "auth_enabled": effective_auth_enabled(db, s.auth_enabled),
        "objects": len(db.list_objects(limit=1000)),
        "cache": (
            {"enabled": False} if cache is None
            else {"enabled": True, "entries": cache.count(),
                  "bytes": cache.size(),
                  "max_bytes": s.cache_max_mb * 1024 * 1024}
        ),
        "max_upload_bytes": s.max_upload_bytes(),
        "time": int(time.time()),
    }


@router.post("/admin/auth/toggle")
async def auth_toggle(request: Request):
    """Flip the auth switch at runtime — no restart. Admin key required.

    When auth is OFF, all endpoints are open (public mode). When ON, the
    configured keys and signed URLs are enforced again.
    """
    require_admin(request)
    db = request.app.state.db
    s = request.app.state.settings
    current = effective_auth_enabled(db, s.auth_enabled)
    db.kv_set(KV_AUTH, "0" if current else "1")
    return JSONResponse({"auth_enabled": not current})


@router.post("/admin/auth/rotate-secret")
async def rotate_secret(request: Request):
    """Generate a fresh HMAC signing secret. Old signed links become invalid
    (410) immediately; callers must mint new links. Admin key required.
    """
    require_admin(request)
    db = request.app.state.db
    secret = new_secret()
    db.kv_set(KV_HMAC_SECRET, secret)
    return {"hmac_secret": secret, "note": "previously minted links are now invalid"}


@router.get("/admin/objects")
async def objects(request: Request, limit: int = 50, offset: int = 0):
    """List stored objects (newest first). Admin key required."""
    require_admin(request)
    db = request.app.state.db
    limit = max(1, min(limit, 500))
    rows = db.list_objects(limit=limit, offset=max(0, offset))
    return {"objects": rows, "count": len(rows)}