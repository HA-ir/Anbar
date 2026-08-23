"""F6: rate limiting (SQLite fixed windows) + LRU disk cache + anbarctl install."""
from __future__ import annotations

import os

from fastapi.testclient import TestClient

from anbar.cache import DiskLRU
from anbar.cli import main as cli_main
from anbar.db import Database
from anbar.main import create_app
from anbar.storage import FakeBackend

UP = {"Authorization": "Bearer test-key"}


def _upload(client, data: bytes, name="f.bin") -> str:
    r = client.post("/api/v1/upload/raw", content=data, headers={**UP, "x-file-name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _app(monkeypatch, backend: FakeBackend, extra_env: dict[str, str]):
    monkeypatch.setenv("ANBAR_BACKEND", "fake")
    for k, v in extra_env.items():
        monkeypatch.setenv(k, v)
    from anbar.config import get_settings
    get_settings.cache_clear()
    try:
        return create_app(backend=backend)
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------- rate limits

def test_download_rate_limit_429_with_retry_after(monkeypatch, tmp_path):
    monkeypatch.setenv("ANBAR_RATE_DOWNLOAD_PER_MIN", "2")
    monkeypatch.setenv("ANBAR_CACHE_ENABLED", "false")
    be = FakeBackend()
    app = _app(monkeypatch, be, {})
    with TestClient(app) as c:
        oid = _upload(c, b"hello")
        assert c.get(f"/f/{oid}", headers=UP).status_code == 200
        assert c.get(f"/f/{oid}", headers=UP).status_code == 200
        r = c.get(f"/f/{oid}", headers=UP)
        assert r.status_code == 429
        assert int(r.headers["retry-after"]) >= 1


def test_download_limit_applied_before_auth(monkeypatch):
    """An unauthenticated hammerer gets 429, not an endless 401 loop."""
    monkeypatch.setenv("ANBAR_RATE_DOWNLOAD_PER_MIN", "1")
    be = FakeBackend()
    app = _app(monkeypatch, be, {})
    with TestClient(app) as c:
        oid = _upload(c, b"hello")
        assert c.get(f"/f/{oid}").status_code == 401  # auth on, no key
        assert c.get(f"/f/{oid}").status_code == 429  # window exhausted


def test_upload_rate_limit_429(monkeypatch):
    monkeypatch.setenv("ANBAR_RATE_UPLOAD_PER_MIN", "1")
    be = FakeBackend()
    app = _app(monkeypatch, be, {})
    with TestClient(app) as c:
        assert c.post("/api/v1/upload/raw", content=b"a", headers=UP).status_code == 200
        r = c.post("/api/v1/upload/raw", content=b"b", headers=UP)
        assert r.status_code == 429


def test_rate_limits_disabled_at_zero(monkeypatch):
    monkeypatch.setenv("ANBAR_RATE_DOWNLOAD_PER_MIN", "0")
    monkeypatch.setenv("ANBAR_RATE_UPLOAD_PER_MIN", "0")
    be = FakeBackend()
    app = _app(monkeypatch, be, {})
    with TestClient(app) as c:
        oid = _upload(c, b"hello")
        for _ in range(25):
            assert c.get(f"/f/{oid}", headers=UP).status_code == 200


def test_rate_check_window_recycles(tmp_path):
    db = Database(tmp_path / "rate.db")
    ok1, _, n1 = db.rate_check("k", 60, 2)
    ok2, _, n2 = db.rate_check("k", 60, 2)
    ok3, ra, n3 = db.rate_check("k", 60, 2)
    assert (ok1, ok2) == (True, True) and n1 == 1 and n2 == 2
    assert ok3 is False and n3 == 3 and ra >= 1
    db.close()


# ---------------------------------------------------------------- LRU cache

def test_cache_off_by_default_no_files(monkeypatch):
    be = FakeBackend()
    app = _app(monkeypatch, be, {})
    with TestClient(app) as c:
        assert app.state.cache is None
        oid = _upload(c, b"x" * 1000)
        c.get(f"/f/{oid}", headers=UP)
        assert c.get("/api/v1/admin/status", headers={"Authorization": "Bearer test-admin-key"})\
            .json()["cache"] == {"enabled": False}


def test_cache_hit_skips_backend(monkeypatch, tmp_path):
    monkeypatch.setenv("ANBAR_CACHE_ENABLED", "true")
    monkeypatch.setenv("ANBAR_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("ANBAR_CACHE_MAX_MB", "10")
    be = FakeBackend()
    app = _app(monkeypatch, be, {})
    with TestClient(app) as c:
        oid = _upload(c, b"A" * 5000)
        r1 = c.get(f"/f/{oid}", headers=UP)
        assert r1.status_code == 200 and r1.content == b"A" * 5000
        assert be.open_calls == 1  # miss filled the cache
        r2 = c.get(f"/f/{oid}", headers=UP)
        assert r2.status_code == 200 and r2.content == b"A" * 5000
        assert be.open_calls == 1  # hit — no backend call
        admin = {"Authorization": "Bearer test-admin-key"}
        st = c.get("/api/v1/admin/status", headers=admin).json()
        assert st["cache"]["entries"] == 1 and st["cache"]["bytes"] == 5000


def test_cache_delete_invalidates(monkeypatch, tmp_path):
    monkeypatch.setenv("ANBAR_CACHE_ENABLED", "true")
    monkeypatch.setenv("ANBAR_CACHE_DIR", str(tmp_path / "cache"))
    be = FakeBackend()
    app = _app(monkeypatch, be, {})
    with TestClient(app) as c:
        oid = _upload(c, b"Z" * 1000)
        c.get(f"/f/{oid}", headers=UP)  # cache it
        r = c.delete(f"/f/{oid}", headers=UP)
        assert r.status_code == 200
        assert app.state.cache.count() == 0  # invalidated
        # files are actually gone from the cache dir
        assert list((tmp_path / "cache").iterdir()) == []


def test_lru_evicts_oldest_first(tmp_path):
    cache = DiskLRU(tmp_path / "c", max_bytes=115)
    p1 = cache.new_entry_path()
    with open(p1, "wb") as f:
        f.write(b"x" * 60)
    cache.add("old", p1, 60)
    p2 = cache.new_entry_path()
    with open(p2, "wb") as f:
        f.write(b"y" * 60)
    cache.add("new", p2, 60)  # 60+60 > 100 → "old" evicted
    assert cache.contains("old") is False
    assert cache.contains("new") is True
    assert cache.size() == 60
    # get() refreshes recency: "new" accessed, then a 50-byte third entry fits
    assert cache.get("new") is not None
    p3 = cache.new_entry_path()
    with open(p3, "wb") as f:
        f.write(b"z" * 50)
    cache.add("third", p3, 50)
    assert cache.contains("new") and cache.contains("third")


def test_lru_skips_oversized_entries(tmp_path):
    cache = DiskLRU(tmp_path / "c", max_bytes=10)
    p = cache.new_entry_path()
    with open(p, "wb") as f:
        f.write(b"x" * 20)
    cache.add("big", p, 20)  # bigger than the whole budget → never cached
    assert cache.contains("big") is False
    try:
        os.unlink(p)
    except OSError:
        pass

def test_cli_install_writes_unit(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ANBAR_BACKEND=bot\n")
    unit = tmp_path / "anbar.service"
    rc = cli_main(["install", "--unit", str(unit), "--env-file", str(env),
                   "--workdir", "/srv/anbar", "--loopback"])
    assert rc == 0
    body = unit.read_text()
    assert "ExecStart=" in body and "anbar.main:create_app" in body
    assert "--host 127.0.0.1" in body
    assert f"EnvironmentFile={env}" in body


def test_cli_install_missing_env_file_fails(tmp_path):
    rc = cli_main(["install", "--unit", str(tmp_path / "u.service"),
                   "--env-file", str(tmp_path / "nope.env"), "--workdir", "/srv/anbar"])
    assert rc == 1
