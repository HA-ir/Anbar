"""Auth primitives (F4): HMAC-signed download links + key verification.

Signed URL format:  /f/{obj_id}?sig=<hex>&exp=<unix-ts>
    sig = HMAC-SHA256(secret, f"{obj_id}:{exp}")

The secret comes from the kv override (after rotate-secret) or settings.
Keys are compared in constant time.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException

from .db import Database

KV_AUTH = "auth_enabled"
KV_HMAC_SECRET = "hmac_secret"


def sign(obj_id: str, exp: int, secret: str) -> str:
    msg = f"{obj_id}:{exp}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def verify_sig(obj_id: str, exp: int, sig: str, secret: str) -> bool:
    if not sig or not exp:
        return False
    expected = sign(obj_id, exp, secret)
    return hmac.compare_digest(expected, sig)


def is_expired(exp: int) -> bool:
    return exp <= int(time.time())


def constant_time_equal(a: str | None, b: str | None) -> bool:
    if a is None or b is None or not a or not b:
        return False
    return hmac.compare_digest(a.encode(), b.encode())


def hash_key(key: str) -> str:
    """Store/compare keys by sha256 digest (raw keys never touch the DB)."""
    return hashlib.sha256(key.encode()).hexdigest()


def effective_auth_enabled(db: Database, default: bool) -> bool:
    """kv override wins (runtime toggle), else the settings default."""
    v = db.kv_get(KV_AUTH)
    if v is None:
        return default
    return v == "1"


def effective_hmac_secret(db: Database, configured: str | None) -> str | None:
    return db.kv_get(KV_HMAC_SECRET) or configured


def new_secret(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


# ── FastAPI dependencies ────────────────────────────────────────────────────
def whoami(request) -> str:
    """Resolve the caller: 'admin' | 'uploader' | 'anon' (constant-time)."""
    settings = request.app.state.settings
    auth = request.headers.get("authorization", "")
    key = auth[7:] if auth.lower().startswith("bearer ") else None
    admin_key = settings.admin_key.get_secret_value() if settings.admin_key else None
    api_key = settings.api_key.get_secret_value() if settings.api_key else None
    if key and admin_key and constant_time_equal(key, admin_key):
        return "admin"
    if key and api_key and constant_time_equal(key, api_key):
        return "uploader"
    return "anon"


def require_uploader(request):
    role = whoami(request)
    if _auth_on(request) and role == "anon":
        raise HTTPException(401, "authentication required",
                            headers={"WWW-Authenticate": "Bearer"})
    return role


def require_admin(request):
    role = whoami(request)
    if _auth_on(request) and role == "anon":
        raise HTTPException(401, "authentication required",
                            headers={"WWW-Authenticate": "Bearer"})
    if role != "admin":
        raise HTTPException(403, "admin key required")
    return role


def _auth_on(request) -> bool:
    s = request.app.state.settings
    return effective_auth_enabled(request.app.state.db, s.auth_enabled)