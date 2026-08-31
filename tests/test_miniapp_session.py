"""QUAL-02: miniapp initData → web session → authenticated API flow."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

from fastapi.testclient import TestClient

BOT_TOKEN = "987654:QUAL02_MINIAPP_TEST_TOKEN"


def _signed_init_data(user_id: int = 12345678, auth_date: int | None = None) -> str:
    auth_date = auth_date if auth_date is not None else int(time.time())
    params = {
        "auth_date": str(auth_date),
        "query_id": "AAQUAL02",
        "user": json.dumps({"id": user_id, "first_name": "Hossein"}),
    }
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    valid_hash = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return (
        f"auth_date={params['auth_date']}&query_id={params['query_id']}"
        f"&user={params['user']}&hash={valid_hash}"
    )


def _boot_with_token(client: TestClient, monkeypatch) -> None:
    """Wire BOT_TOKEN into the app settings (tests run tokenless)."""
    from types import SimpleNamespace

    monkeypatch.setattr(
        type(client.app.state.settings),
        "bot_tokens",
        property(lambda self: [BOT_TOKEN]),
    )


def test_miniapp_session_requires_init_data(client: TestClient):
    r = client.post("/ui/miniapp/session", json={})
    assert r.status_code == 400
    r = client.post("/ui/miniapp/session", data="not json")
    assert r.status_code == 400


def test_miniapp_session_rejects_bad_signature(client: TestClient, monkeypatch):
    _boot_with_token(client, monkeypatch)
    # tampered initData: signature no longer matches
    r = client.post(
        "/ui/miniapp/session",
        json={"init_data": _signed_init_data(user_id=12345678).replace("12345678", "999")},
    )
    assert r.status_code == 401
    # expired initData (older than the 24h window)
    r = client.post(
        "/ui/miniapp/session",
        json={"init_data": _signed_init_data(auth_date=int(time.time()) - 100_000)},
    )
    assert r.status_code == 401


def test_miniapp_session_rejected_without_bot_token(client: TestClient):
    # default test settings have no bot token → endpoint unavailable, not open
    r = client.post("/ui/miniapp/session", json={"init_data": _signed_init_data()})
    assert r.status_code == 503


def test_miniapp_full_flow_sets_admin_session(client: TestClient, monkeypatch):
    _boot_with_token(client, monkeypatch)

    # anon cannot list objects (auth on by default)
    assert client.get("/api/v1/admin/objects").status_code == 401

    r = client.post(
        "/ui/miniapp/session", json={"init_data": _signed_init_data(user_id=4242)}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["role"] == "admin"
    assert body["user_id"] == 4242
    assert "anbar_session" in r.cookies

    # the cookie now authenticates admin API calls (same contract as /ui/login)
    r2 = client.get("/api/v1/admin/objects")
    assert r2.status_code == 200

    r3 = client.get("/ui/me")
    assert r3.json() == {"authed": True, "role": "admin"}


def test_miniapp_session_cookie_role_is_admin_only(client: TestClient, monkeypatch):
    """The mini app session must never silently degrade to anon uploads."""
    _boot_with_token(client, monkeypatch)
    r = client.post("/ui/miniapp/session", json={"init_data": _signed_init_data()})
    assert r.status_code == 200
    # admin-only endpoint proves the role
    status = client.get("/api/v1/admin/status")
    assert status.status_code == 200
