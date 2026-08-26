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

from . import webauth
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
def list_api_keys(db) -> list[dict]:
    """All dynamic uploader keys (v0.8.7): [{id, key, name, created_at}]."""
    import json as _json

    try:
        return _json.loads(db.kv_get("api_keys", "[]") or "[]")
    except Exception:  # noqa: BLE001 - corrupted value behaves like "none"
        return []


def add_api_key(db, name: str) -> dict:
    entry = {
        "id": secrets.token_hex(4),
        "key": new_secret(24),
        "name": (name or "key").strip()[:60],
        "created_at": int(time.time()),
    }
    keys = list_api_keys(db)
    keys.append({k: v for k, v in entry.items() if k != "key"} | {"key": entry["key"]})
    db.kv_set("api_keys", __import__("json").dumps(keys))
    return entry


def revoke_api_key(db, key_id: str) -> bool:
    keys = list_api_keys(db)
    kept = [k for k in keys if k.get("id") != key_id]
    if len(kept) == len(keys):
        return False
    db.kv_set("api_keys", __import__("json").dumps(kept))
    return True


def _match_dynamic_key(key: str, db) -> bool:
    """Constant-time match against every stored uploader key."""
    for k in list_api_keys(db):
        stored = k.get("key", "")
        if stored and constant_time_equal(key, stored):
            return True
    return False


def whoami(request) -> str:
    """Resolve the caller: 'admin' | 'uploader' | 'anon' (constant-time).

    Accepts a `Authorization: Bearer <key>` header OR a valid web session
    cookie (issued by the F7 UI). The bearer header wins when present.
    """
    settings = request.app.state.settings
    auth = request.headers.get("authorization", "")
    key = auth[7:] if auth.lower().startswith("bearer ") else None
    admin_key = settings.admin_key.get_secret_value() if settings.admin_key else None
    api_key = settings.api_key.get_secret_value() if settings.api_key else None
    if key and admin_key and constant_time_equal(key, admin_key):
        return "admin"
    if key and (
        (api_key and constant_time_equal(key, api_key))
        or _match_dynamic_key(key, request.app.state.db)
    ):
        return "uploader"
    # F7: signed web session cookie (no key in the cookie). Browsers can hold
    # DUPLICATE anbar_session cookies (e.g. one created pre-Secure, or via a
    # redirect) and send them all in creation order; Starlette's
    # request.cookies keeps only the LAST. If the stale invalid one sorts
    # last, the user is anonymous forever until they clear cookies by hand.
    # Try every occurrence instead — any valid session wins.
    cookie_header = request.headers.get("cookie", "")
    if cookie_header and "anbar_session=" in cookie_header:
        db = request.app.state.db
        for pair in cookie_header.split(";"):
            pair = pair.strip()
            if not pair.startswith("anbar_session="):
                continue
            try:
                role = webauth.verify_session(db, pair.split("=", 1)[1])
            except Exception:  # pragma: no cover - bad cookie must never 500
                role = None
            if role:
                return role
    return "anon"


def require_uploader(request):
    role = whoami(request)
    if _auth_on(request) and role == "anon":
        raise HTTPException(401, "authentication required", headers={"WWW-Authenticate": "Bearer"})
    return role


def require_admin(request):
    role = whoami(request)
    if _auth_on(request) and role == "anon":
        raise HTTPException(401, "authentication required", headers={"WWW-Authenticate": "Bearer"})
    if role != "admin":
        raise HTTPException(403, "admin key required")
    return role


def _auth_on(request) -> bool:
    s = request.app.state.settings
    return effective_auth_enabled(request.app.state.db, s.auth_enabled)
