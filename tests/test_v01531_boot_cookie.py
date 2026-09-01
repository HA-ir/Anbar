"""v0.15.31 — the REAL root cause of "no previews, downloads fail".

boot() trusted /ui/me, which authenticates via the Bearer header too. With an
expired/absent session cookie the UI still showed the app (Bearer works for
/api), but every keyless media URL (<img>/<video>/<a download>) — which only
carries the cookie — got 401. Fix: boot() (re)logins with the stored key to
mint a fresh cookie BEFORE trusting /ui/me.
"""
from __future__ import annotations

from starlette.testclient import TestClient

UP = {"Authorization": "Bearer test-key"}


def _upload(client: TestClient, name: str) -> str:
    obj = client.post(
        "/api/v1/upload/raw",
        content=b"Z" * 64,
        headers={**UP, "X-File-Name": name, "Content-Type": "application/octet-stream"},
    ).json()
    return obj["id"]


def test_media_requires_cookie_not_bearer(client: TestClient):
    """<img>/<a> requests carry NO Bearer — without a cookie they 401 (SEC-02 matrix)."""
    oid = _upload(client, "x.bin")
    # anonymous → 401
    assert client.get(f"/f/{oid}").status_code == 401
    # SEC-02: admin key in ?k= stays rejected for anonymous media requests
    # (with a valid Bearer header the request is authorized by the HEADER,
    #  so a 200 there is correct — SEC-02 only bans the ?k= channel itself)
    r = client.get(f"/f/{oid}?k=test-admin-key")
    assert r.status_code == 401


def test_login_mints_cookie_that_authorizes_media(client: TestClient):
    """The boot() contract: POST /ui/login {key} → cookie → keyless media URL 200."""
    oid = _upload(client, "y.bin")

    r = client.post("/ui/login", json={"key": "test-admin-key"})
    assert r.status_code == 200

    r2 = client.get(f"/f/{oid}")
    assert r2.status_code == 200


def test_boot_relogin_flow_cookie_death_recovery(client: TestClient):
    """Simulate the user's scenario: key in localStorage, cookie expired.
    login again (what boot() now always does) → fresh cookie → media 200."""
    oid = _upload(client, "z.bin")

    first = client.post("/ui/login", json={"key": "test-admin-key"})
    assert first.status_code == 200
    # simulate expiry: drop the cookie entirely
    client.cookies.clear()
    # media now fails (this was the bug: UI stayed 'authed' via Bearer)
    assert client.get(f"/f/{oid}").status_code == 401
    # boot() fix: silent re-login with the stored key
    second = client.post("/ui/login", json={"key": "test-admin-key"})
    assert second.status_code == 200
    assert client.get(f"/f/{oid}").status_code == 200
