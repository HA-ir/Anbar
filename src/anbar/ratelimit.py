"""Fixed-window rate limits backed by SQLite (F6). No Redis required."""

from __future__ import annotations

import hashlib

from fastapi import HTTPException, Request

from .db import Database

_WINDOW_S = 60


def _client_ip(request: Request) -> str:
    """Best-effort client IP for rate limiting.

    SEC-01 (v0.15.20): X-Forwarded-For is only trusted when the TCP peer is
    a loopback address — i.e. the request actually arrived through the
    local reverse proxy. A direct client (or one spoofing XFF on a proxied
    chain it doesn't control) is rate-limited by its real socket address.
    With nginx's `X-Forwarded-For $proxy_add_x_forwarded_for`, the LAST
    entry is the address nginx saw (the real client), so we take the last
    hop, not the first (which is client-controlled).
    """
    peer = request.client.host if request.client else "?"
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd and peer in ("127.0.0.1", "::1", "localhost"):
        return fwd.split(",")[-1].strip()
    return peer


def _raise_limited(retry_after: int) -> None:
    raise HTTPException(
        status_code=429,
        detail="rate limited",
        headers={"Retry-After": str(retry_after)},
    )


def limit_download(db: Database, request: Request, obj_id: str, limit: int) -> None:
    """Per (client IP, object id) per minute. Applied before auth on purpose:
    an anonymous hammerer gets 429, not an endless 401/403 loop."""
    if limit <= 0:
        return
    ok, retry_after, _n = db.rate_check(f"dl:{_client_ip(request)}:{obj_id}", _WINDOW_S, limit)
    if not ok:
        _raise_limited(retry_after)


def limit_upload(db: Database, request: Request, limit: int) -> None:
    """Per API key per minute. The key is hashed — never stored raw."""
    if limit <= 0:
        return
    auth = request.headers.get("authorization", "")
    digest = hashlib.sha256(auth.encode()).hexdigest()[:16] if auth else "anon"
    ok, retry_after, _n = db.rate_check(f"up:{digest}", _WINDOW_S, limit)
    if not ok:
        _raise_limited(retry_after)


def limit_login(db: Database, request: Request, limit: int) -> None:
    """Per client IP per minute (F7 web login — throttles brute force)."""
    if limit <= 0:
        return
    ok, retry_after, _n = db.rate_check(f"lg:{_client_ip(request)}", _WINDOW_S, limit)
    if not ok:
        _raise_limited(retry_after)
