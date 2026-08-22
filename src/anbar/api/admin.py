"""Admin endpoints (F4): status, auth toggle, secret rotation, object listing.

F8 adds runtime settings (rate limits, size ceiling, session TTL, cache
budget) and a cache purge.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from .. import runtime
from ..auth import (
    KV_AUTH,
    KV_HMAC_SECRET,
    add_api_key,
    effective_auth_enabled,
    list_api_keys,
    new_secret,
    require_admin,
    revoke_api_key,
)
from ..cache import DiskLRU

router = APIRouter()


def _env_defaults(s) -> dict[str, int]:
    return {
        "rate_download": s.rate_download_per_min,
        "rate_upload": s.rate_upload_per_min,
        "rate_login": s.rate_login_per_min,
        "max_upload_mb": s.max_upload_mb,
        "web_session_ttl": s.web_session_ttl,
        "cache_mb": s.cache_max_mb,
    }


@router.get("/admin/status")
async def status(request: Request):
    s = request.app.state.settings
    db = request.app.state.db
    backend = request.app.state.backend
    cache = getattr(request.app.state, "cache", None)
    cache_mb = runtime.get_int(db, "cache_mb", s.cache_max_mb)
    return {
        "status": "ok",
        "backend": getattr(backend, "name", s.backend.value),
        "auth_enabled": effective_auth_enabled(db, s.auth_enabled),
        "objects": len(db.list_objects(limit=1000)),
        "cache": (
            {"enabled": False} if cache is None
            else {"enabled": True, "entries": cache.count(),
                  "bytes": cache.size(),
                  "max_bytes": cache_mb * 1024 * 1024}
        ),
        # master switch from .env — UI shows "disabled" when false
        "cache_master": s.cache_enabled,
        "max_upload_bytes": runtime.get_int(db, "max_upload_mb", s.max_upload_mb)
        * 1024 * 1024,
        "settings": runtime.effective(db, _env_defaults(s)),
        "time": int(time.time()),
    }


@router.get("/admin/settings")
async def settings_get(request: Request):
    """Effective settings + env defaults + override flags. Admin key required."""
    require_admin(request)
    db = request.app.state.db
    s = request.app.state.settings
    return {"settings": runtime.effective(db, _env_defaults(s))}


@router.post("/admin/settings")
async def settings_update(request: Request):
    """Update any subset of the runtime settings. Admin key required.

    Body: ``{"rate_download": 50, "cache_mb": 0, ...}`` — unknown keys or
    out-of-range values → 422.
    """
    require_admin(request)
    db = request.app.state.db
    s = request.app.state.settings
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "expected JSON object") from None
    if not isinstance(body, dict) or not body:
        raise HTTPException(400, "expected non-empty JSON object")
    changed = {}
    for name, value in body.items():
        if name not in runtime.SPEC:
            raise HTTPException(422, f"unknown setting: {name}")
        try:
            changed[name] = runtime.set_int(db, name, value)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
    if "cache_mb" in changed:
        _sync_cache(request.app, db)
    return {"changed": changed,
            "settings": runtime.effective(db, _env_defaults(s))}


def _sync_cache(app, db) -> None:
    """(Re)build or tear down the LRU cache instance.

    ``ANBAR_CACHE_ENABLED`` is the master switch: when it is off, the disk
    cache must stay off regardless of any ``cache_mb`` override, preserving
    the zero-retention default.
    """
    s = app.state.settings
    cache_mb = runtime.get_int(db, "cache_mb", s.cache_max_mb)
    old = getattr(app.state, "cache", None)
    if old is not None:
        old.close()
    app.state.cache = (
        DiskLRU(s.cache_dir, cache_mb * 1024 * 1024)
        if s.cache_enabled and cache_mb else None
    )


@router.post("/admin/settings/reset")
async def settings_reset(request: Request):
    """Drop overrides (back to .env defaults). Body: {"keys": [...]} or all."""
    require_admin(request)
    db = request.app.state.db
    s = request.app.state.settings
    try:
        body = await request.json()
    except Exception:
        body = {}
    keys = body.get("keys") if isinstance(body, dict) else None
    names = [k for k in (keys or list(runtime.SPEC))]
    unknown = [k for k in names if k not in runtime.SPEC]
    if unknown:
        raise HTTPException(422, f"unknown setting: {', '.join(unknown)}")
    reset = {k: runtime.reset(db, k) for k in names}
    if "cache_mb" in names:
        _sync_cache(request.app, db)
    return {"reset": reset,
            "settings": runtime.effective(db, _env_defaults(s))}


@router.post("/admin/cache/purge")
async def cache_purge(request: Request):
    """Evict all cached objects (scratch space only — nothing is lost)."""
    require_admin(request)
    db = request.app.state.db
    app = request.app
    old = getattr(app.state, "cache", None)
    purged = old.count() if old is not None else 0
    _sync_cache(app, db)  # rebuild empty, or tear down if disabled
    return {"purged": purged}


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


# ── API key management (v0.8.7) ──────────────────────────────────────────────
@router.get("/admin/api-keys")
async def api_keys_list(request: Request):
    require_admin(request)
    keys = list_api_keys(request.app.state.db)
    # never echo full keys after creation — only id/name/created_at
    return {"keys": [{k: v for k, v in k_.items() if k != "key"} for k_ in keys]}


@router.post("/admin/api-keys")
async def api_keys_create(request: Request):
    require_admin(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    name = (body or {}).get("name", "") if isinstance(body, dict) else ""
    entry = add_api_key(request.app.state.db, name or "")
    return {"id": entry["id"], "name": entry["name"], "key": entry["key"],
            "note": "copy this key now — it is not shown again"}


@router.delete("/admin/api-keys/{key_id}")
async def api_keys_revoke(request: Request, key_id: str):
    require_admin(request)
    ok = revoke_api_key(request.app.state.db, key_id)
    if not ok:
        raise HTTPException(404, "unknown key id")
    return {"revoked": key_id}