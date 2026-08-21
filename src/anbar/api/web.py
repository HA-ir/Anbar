"""Web UI (F7): a minimal password-gated page for list / upload / download.

Login accepts the **admin** key, then sets a signed, short-lived session
cookie (see webauth). After that the browser never sends the raw key again:
all same-origin requests carry the cookie, and ``whoami`` (in auth.py)
resolves the role from it. The UI reuses the existing JSON API — no
duplicated storage logic. Downloads open the same streaming ``/f/{id}``
route; while the cookie is valid the browser needs no per-file bearer key.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .. import __version__
from ..auth import constant_time_equal, whoami
from ..ratelimit import limit_login
from ..webauth import COOKIE, issue_session

router = APIRouter()


def _is_https(request: Request) -> bool:
    if request.headers.get("x-forwarded-proto", "").lower() == "https":
        return True
    return request.url.scheme == "https"


def _set_session(response: JSONResponse, request: Request, value: str | None,
                 max_age: int) -> None:
    response.delete_cookie(COOKIE, httponly=True, samesite="lax", secure=_is_https(request))
    if value:
        response.set_cookie(
            COOKIE, value, max_age=max_age, httponly=True, samesite="lax",
            secure=_is_https(request), path="/",
        )


@router.post("/ui/login")
async def login(request: Request):
    """Validate the key and issue a session cookie. Admin key only (the UI
    is a personal owner tool: full list + delete + share)."""
    settings = request.app.state.settings
    db = request.app.state.db
    limit_login(db, request, settings.rate_login_per_min)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "expected JSON {key}") from None
    key = (body or {}).get("key", "")
    admin_key = settings.admin_key.get_secret_value() if settings.admin_key else None
    if not admin_key or not key or not constant_time_equal(key, admin_key):
        raise HTTPException(401, "invalid key")
    ttl = settings.web_session_ttl
    resp = JSONResponse({"ok": True, "role": "admin"})
    _set_session(resp, request, issue_session(db, ttl, "admin"), ttl)
    return resp


@router.post("/ui/logout")
async def logout(request: Request):
    resp = JSONResponse({"ok": True})
    _set_session(resp, request, None, 0)
    return resp


@router.get("/ui/me")
async def me(request: Request):
    role = whoami(request)
    return {"authed": role in ("admin", "uploader"), "role": role}


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
async def index(request: Request):
    return HTMLResponse(_render())


def _render() -> str:
    tpl = (Path(__file__).parent.parent / "ui" / "index.html").read_text(encoding="utf-8")
    return tpl.replace("__VERSION__", __version__)