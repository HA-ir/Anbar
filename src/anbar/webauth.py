"""Web UI sessions (F7): short-lived, stateless, HMAC-signed cookies.

The raw key never appears in the cookie. The value is ``{exp}:{tag}:{sig}``:

    sig = HMAC-SHA256(secret, f"anbar-ui:{role}:{exp}:{tag}")

The signing secret is a dedicated value stored in the kv table (created on
first login), so rotating the download-link HMAC secret does not invalidate
web sessions — and vice versa. Sessions are short (default 12 h) and the
cookie is HttpOnly + SameSite=Lax (+ Secure on https deployments).
"""
from __future__ import annotations

import hmac
import secrets
import time

from .db import Database

KV_SESSION_SECRET = "ui_session_secret"
COOKIE = "anbar_session"


def _secret(db: Database) -> str:
    s = db.kv_get(KV_SESSION_SECRET)
    if s:
        return s
    s = secrets.token_urlsafe(32)
    db.kv_set(KV_SESSION_SECRET, s)
    return s


def issue_session(db: Database, ttl_seconds: int, role: str) -> str:
    """Create a fresh signed session value for `role`, valid `ttl_seconds`."""
    tag = secrets.token_urlsafe(16)
    exp = int(time.time()) + ttl_seconds
    return f"{exp}:{tag}:{_sign(_secret(db), role, exp, tag)}"


def verify_session(db: Database, value: str | None) -> str | None:
    """Return 'admin'|'uploader' if `value` is a valid session, else None."""
    if not value or value.count(":") != 2:
        return None
    exp_s, tag, sig = value.split(":")
    try:
        exp = int(exp_s)
    except ValueError:
        return None
    if exp <= int(time.time()):
        return None
    secret = _secret(db)
    for role in ("admin", "uploader"):
        if hmac.compare_digest(_sign(secret, role, exp, tag), sig):
            return role
    return None


def _sign(secret: str, role: str, exp: int, tag: str) -> str:
    import hashlib

    msg = f"anbar-ui:{role}:{exp}:{tag}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()