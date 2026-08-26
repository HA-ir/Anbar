"""F8 — runtime settings: overrides, validation, live application, reset."""

from __future__ import annotations

ADMIN = "test-admin-key"
API = "test-key"


def _authed(client):
    client.post("/ui/login", json={"key": ADMIN})


def test_settings_get_defaults(client):
    _authed(client)
    r = client.get("/api/v1/admin/settings")
    assert r.status_code == 200
    s = r.json()["settings"]
    assert s["rate_download"]["default"] == 1000  # conftest env default
    assert s["rate_download"]["value"] == 1000
    assert s["rate_download"]["overridden"] is False
    assert s["max_upload_mb"]["default"] == 2000
    assert s["cache_mb"]["default"] == 512


def test_settings_update_and_persist(client):
    _authed(client)
    r = client.post("/api/v1/admin/settings", json={"rate_download": 2, "max_upload_mb": 15})
    assert r.status_code == 200, r.text
    s = r.json()["settings"]
    assert s["rate_download"]["value"] == 2
    assert s["rate_download"]["overridden"] is True
    assert s["max_upload_mb"]["value"] == 15
    # re-read on the same app: kv override must still be in effect
    s2 = client.get("/api/v1/admin/settings").json()["settings"]
    assert s2["rate_download"]["value"] == 2
    assert s2["rate_download"]["overridden"] is True


def test_settings_rejects_bad_values(client):
    _authed(client)
    assert client.post("/api/v1/admin/settings", json={"nope": 1}).status_code == 422
    assert client.post("/api/v1/admin/settings", json={"rate_download": -1}).status_code == 422
    assert client.post("/api/v1/admin/settings", json={"rate_download": 999999}).status_code == 422
    # invalid values must not leak
    s = client.get("/api/v1/admin/settings").json()["settings"]
    assert s["rate_download"]["value"] == s["rate_download"]["default"]


def test_settings_requires_auth(client):
    assert client.get("/api/v1/admin/settings").status_code == 401
    assert client.post("/api/v1/admin/settings", json={"rate_download": 5}).status_code == 401


def test_rate_download_live(client):
    _authed(client)
    # tighten download limit to 2/min (override the generous env default)
    assert client.post("/api/v1/admin/settings", json={"rate_download": 2}).status_code == 200
    import os
    import uuid

    name = "rt-%s.bin" % uuid.uuid4().hex[:8]  # noqa: UP031 — kept for readability
    data = os.urandom(4096)
    up = client.post(
        "/api/v1/upload",
        headers={"Authorization": f"Bearer {API}"},
        files={"file": (name, data, "application/octet-stream")},
    )
    assert up.status_code == 200, up.text
    obj = up.json()["id"]
    h = {"Authorization": f"Bearer {API}"}
    assert client.get(f"/f/{obj}", headers=h).status_code == 200
    assert client.get(f"/f/{obj}", headers=h).status_code == 200
    blocked = client.get(f"/f/{obj}", headers=h)
    assert blocked.status_code == 429
    assert "retry-after" in {k.lower() for k in blocked.headers}


def test_cache_purge(client):
    _authed(client)
    r = client.post("/api/v1/admin/cache/purge")
    assert r.status_code == 200
    assert "purged" in r.json()


def test_status_reports_effective_settings(client):
    _authed(client)
    client.post("/api/v1/admin/settings", json={"rate_upload": 7})
    st = client.get("/api/v1/admin/status").json()
    assert st["settings"]["rate_upload"]["value"] == 7
    assert st["settings"]["rate_upload"]["overridden"] is True


def test_settings_reset(client):
    _authed(client)
    client.post("/api/v1/admin/settings", json={"rate_upload": 7})
    r = client.post("/api/v1/admin/settings/reset", json={"keys": ["rate_upload"]})
    assert r.status_code == 200, r.text
    assert r.json()["reset"]["rate_upload"] is True
    s = r.json()["settings"]
    assert s["rate_upload"]["value"] == s["rate_upload"]["default"]
    assert s["rate_upload"]["overridden"] is False


def test_cache_stays_off_when_master_disabled(client):
    """Regression: changing cache_mb must NOT enable the disk cache while
    ANBAR_CACHE_ENABLED=false (the zero-retention default)."""
    _authed(client)
    assert client.app.state.cache is None
    r = client.post("/api/v1/admin/settings", json={"cache_mb": 512})
    assert r.status_code == 200, r.text
    assert client.app.state.cache is None
    st = client.get("/api/v1/admin/status").json()
    assert st["cache_master"] is False
    assert st["cache"]["enabled"] is False


def test_cache_mb_zero_toggles_live(monkeypatch, tmp_path):
    """With the master switch ON, cache_mb=0 disables the cache at runtime
    and resetting restores the env budget."""
    from fastapi.testclient import TestClient

    from anbar.config import get_settings
    from anbar.main import create_app
    from anbar.storage import FakeBackend

    monkeypatch.setenv("ANBAR_CACHE_ENABLED", "true")
    monkeypatch.setenv("ANBAR_CACHE_DIR", str(tmp_path / "cache"))
    get_settings.cache_clear()
    app = create_app(backend=FakeBackend())
    with TestClient(app) as c:
        c.post("/ui/login", json={"key": ADMIN})
        assert app.state.cache is not None  # master ON + default 512MB
        assert c.post("/api/v1/admin/settings", json={"cache_mb": 0}).status_code == 200
        assert app.state.cache is None  # torn down live
        assert (
            c.post("/api/v1/admin/settings/reset", json={"keys": ["cache_mb"]}).status_code == 200
        )
        assert app.state.cache is not None  # back to env default


def test_mtproto_export_conns_toggle(client):
    """mtproto_export_conns: default 0, settable, clamped 0-8, persisted."""
    _authed(client)
    s = client.get("/api/v1/admin/settings").json()["settings"]
    assert s["mtproto_export_conns"]["default"] == 0
    assert (
        client.post("/api/v1/admin/settings", json={"mtproto_export_conns": 4}).status_code == 200
    )
    s = client.get("/api/v1/admin/settings").json()["settings"]
    assert s["mtproto_export_conns"]["value"] == 4
    assert s["mtproto_export_conns"]["overridden"] is True
    # out of range rejected
    assert (
        client.post("/api/v1/admin/settings", json={"mtproto_export_conns": 9}).status_code == 422
    )


async def _noop():
    return None


def test_set_export_conns_live_on_backend(client):
    """POSTing the setting applies it to a live mtproto backend instance."""
    from fastapi.testclient import TestClient

    from anbar.config import get_settings
    from anbar.main import create_app
    from anbar.storage.mtproto_backend import MTProtoBackend

    class _StubClient:
        async def disconnect(self):
            pass

    be = MTProtoBackend(api_id=1, api_hash="h", session_file="x", client=_StubClient())
    be.connect = lambda: _noop()  # no real session in tests
    get_settings.cache_clear()
    app = create_app(backend=be)
    with TestClient(app) as c:
        c.post("/ui/login", json={"key": ADMIN})
        r = c.post("/api/v1/admin/settings", json={"mtproto_export_conns": 3})
        assert r.status_code == 200, r.text
        assert be.export_conns == 3
        # disabling tears down (empty pool) and flips the flag off
        assert c.post("/api/v1/admin/settings", json={"mtproto_export_conns": 0}).status_code == 200
        assert be.export_conns == 0
