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

from .. import __version__, runtime
from ..auth import constant_time_equal, verify_telegram_init_data, whoami
from ..ratelimit import limit_login
from ..webauth import COOKIE, issue_session

router = APIRouter()


def _is_https(request: Request) -> bool:
    if request.headers.get("x-forwarded-proto", "").lower() == "https":
        return True
    return request.url.scheme == "https"


def _set_session(response: JSONResponse, request: Request, value: str | None, max_age: int) -> None:
    # NOTE: never pair delete_cookie with set_cookie on the same response —
    # some browsers/CDN paths apply the deletion (Max-Age=0) LAST and the
    # fresh session is wiped before it is ever stored, so login "succeeds"
    # but every following request is anonymous. Setting the cookie alone
    # overwrites any old value anyway.
    if value:
        response.set_cookie(
            COOKIE,
            value,
            max_age=max_age,
            httponly=True,
            samesite="lax",
            secure=_is_https(request),
            path="/",
        )
    else:
        response.delete_cookie(COOKIE, httponly=True, samesite="lax", secure=_is_https(request))


@router.post("/ui/login")
async def login(request: Request):
    """Validate the key and issue a session cookie. Admin key only (the UI
    is a personal owner tool: full list + delete + share)."""
    settings = request.app.state.settings
    db = request.app.state.db
    limit_login(db, request, runtime.get_int(db, "rate_login", settings.rate_login_per_min))
    try:
        body = await request.json()
        if not isinstance(body, dict):  # arrays/strings/scalars → 400, not 500
            raise ValueError("body must be a JSON object")
    except Exception:
        raise HTTPException(400, "expected JSON {key}") from None
    key = (body or {}).get("key", "")
    admin_key = settings.admin_key.get_secret_value() if settings.admin_key else None
    if not admin_key or not key or not constant_time_equal(key, admin_key):
        raise HTTPException(401, "invalid key")
    ttl = runtime.get_int(db, "session_ttl", settings.web_session_ttl)
    db.log_audit("auth.login", actor="admin", ip=request.client.host if request.client else None)
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


@router.post("/ui/miniapp/session")
async def miniapp_session(request: Request):
    """QUAL-02: exchange Telegram WebApp initData for a web session cookie.

    initData is cryptographically verified against the bot token (HMAC per
    Telegram's spec, `auth.verify_telegram_init_data`). Proves "a real
    Telegram user opened THIS bot's mini app" — the mini app is an owner
    tool, so the resulting session carries the admin role exactly like
    /ui/login. Rate-limited like the password login (brute-force surface:
    none — a wrong signature is rejected before any cookie is minted).
    """
    settings = request.app.state.settings
    db = request.app.state.db
    limit_login(db, request, runtime.get_int(db, "rate_login", settings.rate_login_per_min))
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("body must be a JSON object")
    except Exception:
        raise HTTPException(400, "expected JSON {init_data}") from None
    init_data = (body or {}).get("init_data", "")
    if not init_data or not isinstance(init_data, str):
        raise HTTPException(400, "init_data required")

    tokens = settings.bot_tokens
    if not tokens:
        raise HTTPException(503, "no bot token configured")

    ok = any(verify_telegram_init_data(init_data, t) for t in tokens)
    if not ok:
        db.log_audit(
            "auth.miniapp_denied",
            actor="anon",
            ip=request.client.host if request.client else None,
        )
        raise HTTPException(401, "invalid initData")

    # who: extract the verified Telegram user for the audit trail only —
    # the signature already guarantees these fields are authentic
    import json as _json
    import urllib.parse as _up

    tg_user = None
    try:
        for k, v in _up.parse_qsl(init_data, keep_blank_values=True):
            if k == "user":
                tg_user = (_json.loads(v) or {}).get("id")
                break
    except Exception:  # noqa: BLE001
        tg_user = None

    ttl = runtime.get_int(db, "session_ttl", settings.web_session_ttl)
    db.log_audit(
        "auth.miniapp",
        actor=str(tg_user) if tg_user is not None else "telegram-user",
        ip=request.client.host if request.client else None,
    )
    resp = JSONResponse({"ok": True, "role": "admin", "user_id": tg_user})
    _set_session(resp, request, issue_session(db, ttl, "admin"), ttl)
    return resp


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
async def index(request: Request):
    return HTMLResponse(_render())


@router.get("/manifest.webmanifest", include_in_schema=False)
async def manifest():
    from fastapi.responses import Response

    p = _ui_dir() / "manifest.webmanifest"
    return Response(
        content=p.read_text(encoding="utf-8") if p.exists() else "{}",
        media_type="application/manifest+json",
    )


@router.get("/icon.svg", include_in_schema=False)
async def icon():
    from fastapi.responses import Response

    p = _ui_dir() / "icon.svg"
    return Response(
        content=p.read_text(encoding="utf-8") if p.exists() else "", media_type="image/svg+xml"
    )


@router.get("/tg-app", response_class=HTMLResponse, include_in_schema=False)
async def telegram_miniapp(request: Request):
    """Serve Telegram Mini App interface."""
    p = _ui_dir() / "miniapp.html"
    return HTMLResponse(p.read_text(encoding="utf-8") if p.exists() else "<h1>Anbar Mini App</h1>")


def _ui_dir() -> Path:
    return Path(__file__).parent.parent / "ui"


def _render() -> str:
    tpl = (Path(__file__).parent.parent / "ui" / "index.html").read_text(encoding="utf-8")
    return tpl.replace("__VERSION__", __version__)
