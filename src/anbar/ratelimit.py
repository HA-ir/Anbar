"""Fixed-window rate limits backed by SQLite (F6). No Redis required."""
from __future__ import annotations

import hashlib

from fastapi import HTTPException, Request

from .db import Database

_WINDOW_S = 60


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _raise_limited(retry_after: int) -> None:
    raise HTTPException(
        status_code=429, detail="rate limited",
        headers={"Retry-After": str(retry_after)},
    )


def limit_download(db: Database, request: Request, obj_id: str, limit: int) -> None:
    """Per (client IP, object id) per minute. Applied before auth on purpose:
    an anonymous hammerer gets 429, not an endless 401/403 loop."""
    if limit <= 0:
        return
    ok, retry_after, _n = db.rate_check(f"dl:{_client_ip(request)}:{obj_id}",
                                        _WINDOW_S, limit)
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