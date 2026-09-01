"""v0.15.37 — cache master switch is runtime-tunable (no .env/restart needed)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from anbar.config import get_settings
from anbar.main import create_app
from anbar.storage import FakeBackend

ADMIN = "test-admin-key"


def _boot(monkeypatch, tmp_path):
    monkeypatch.setenv("ANBAR_CACHE_DIR", str(tmp_path / "cache"))
    get_settings.cache_clear()
    app = create_app(backend=FakeBackend())
    return TestClient(app)


def test_cache_enabled_runtime_toggle(monkeypatch, tmp_path):
    """cache_enabled=1 turns the disk cache on live; 0 tears it down live."""
    with _boot(monkeypatch, tmp_path) as c:  # env default: master OFF
        c.post("/ui/login", json={"key": ADMIN})
        assert c.app.state.cache is None

        r = c.post("/api/v1/admin/settings", json={"cache_enabled": 1})
        assert r.status_code == 200, r.text
        assert c.app.state.cache is not None  # enabled live, no restart

        st = c.get("/api/v1/admin/status").json()
        assert st["cache_master"] is True
        assert st["cache"]["enabled"] is True

        r = c.post("/api/v1/admin/settings", json={"cache_enabled": 0})
        assert r.status_code == 200, r.text
        assert c.app.state.cache is None  # torn down live
        st = c.get("/api/v1/admin/status").json()
        assert st["cache_master"] is False


def test_cache_enabled_out_of_range_rejected(monkeypatch, tmp_path):
    with _boot(monkeypatch, tmp_path) as c:
        c.post("/ui/login", json={"key": ADMIN})
        assert c.post("/api/v1/admin/settings", json={"cache_enabled": 2}).status_code == 422
        assert c.post("/api/v1/admin/settings", json={"cache_enabled": -1}).status_code == 422


def test_cache_enabled_survives_restart(monkeypatch, tmp_path):
    """The kv override (not the env) governs boot: toggle ON, reboot app → ON."""
    from anbar.db import Database

    db_path = tmp_path / "anbar.db"
    monkeypatch.setenv("ANBAR_DB_PATH", str(db_path))
    monkeypatch.setenv("ANBAR_CACHE_DIR", str(tmp_path / "cache"))
    get_settings.cache_clear()
    app = create_app(backend=FakeBackend())
    with TestClient(app) as c:
        c.post("/ui/login", json={"key": ADMIN})
        assert c.app.state.cache is None
        c.post("/api/v1/admin/settings", json={"cache_enabled": 1})
    # "restart": fresh app instance over the same persisted DB — state.cache
    # is set inside the lifespan, so enter the TestClient context first.
    get_settings.cache_clear()
    app2 = create_app(backend=FakeBackend())
    with TestClient(app2):
        assert app2.state.cache is not None
        app2.state.cache.close()


def test_env_default_false_with_no_override_keeps_cache_off(monkeypatch, tmp_path):
    """No kv override + env default off → boot with cache off (old default kept)."""
    with _boot(monkeypatch, tmp_path) as c:
        c.post("/ui/login", json={"key": ADMIN})
        assert c.app.state.cache is None
