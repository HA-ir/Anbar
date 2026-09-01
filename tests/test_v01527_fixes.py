"""BUG-v0.15.27 regression tests.

Covers the two real production failures found during the v0.15.27 E2E pass:

1. ``_write_env_dict`` silently no-oped when the .env is a bind-mounted
   single file (mkstemp in a root-owned dir → EACCES, os.replace → EBUSY).
   The in-place fallback must keep the write working and honour a .bak
   backup, and the endpoint must NOT report ok when persistence fails.

2. Album TTL: ``/f/album`` with ``ttl`` must embed per-item ``exp`` values
   equal to the album expiry (24h default), and ``ttl: 0`` must mean never.
"""

from __future__ import annotations

import json
import os
import time

from starlette.testclient import TestClient

from anbar.api import admin as admin_mod

ADMIN = {"Authorization": "Bearer test-admin-key"}


# ── helpers ──────────────────────────────────────────────────────────────────
def _authed(client: TestClient) -> None:
    client.post("/ui/login", json={"key": "test-admin-key"})


def _upload(
    client: TestClient, name: str, data: bytes, ct: str = "application/octet-stream"
) -> str:
    r = client.post(
        "/api/v1/upload",
        files={"file": (name, data, ct)},
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ── 1. bind-mount .env write fallback ───────────────────────────────────────
def _make_bindmount_like_env(tmp_path, pytestconfig=None):
    """Create a .env that behaves like a bind-mounted single file.

    A bind mount makes rename()/replace() on the file itself fail with
    EBUSY, and the containing directory is typically root-owned (mkstemp
    → EACCES). We emulate with a directory that denies file creation and
    monkeypatch os.replace to raise EBUSY for the env path.
    """
    env = tmp_path / ".env"
    env.write_text("ANBAR_BACKEND=bot\nANBAR_BOT_TOKENS=111:AAA\n", encoding="utf-8")

    # make dir read-only so mkstemp fails like the prod root-owned dir
    d = tmp_path
    d.chmod(0o555)

    real_replace = os.replace

    def fake_replace(src, dst, *a, **kw):
        if str(dst) == str(env) or str(src) == str(env):
            raise OSError(16, "Device or resource busy")  # EBUSY
        return real_replace(src, dst, *a, **kw)

    return env, fake_replace


def test_write_env_dict_inplace_fallback_on_bindmount(tmp_path, monkeypatch):
    env, fake_replace = _make_bindmount_like_env(tmp_path)
    monkeypatch.setattr(os, "replace", fake_replace)
    try:
        ok = admin_mod._write_env_dict(
            env, {"ANBAR_BOT_TOKENS": "111:AAA, 222:BBB"}
        )
        assert ok, "in-place fallback must succeed when atomic path is blocked"
        d = admin_mod._read_env_dict(env)
        assert d["ANBAR_BOT_TOKENS"] == "111:AAA, 222:BBB"
        assert d["ANBAR_BACKEND"] == "bot"  # untouched keys preserved
    finally:
        tmp_path.chmod(0o755)


def test_write_env_dict_adds_new_key_via_fallback(tmp_path, monkeypatch):
    env, fake_replace = _make_bindmount_like_env(tmp_path)
    monkeypatch.setattr(os, "replace", fake_replace)
    try:
        ok = admin_mod._write_env_dict(env, {"ANBAR_CHANNEL_ID": "-100123"})
        assert ok
        d = admin_mod._read_env_dict(env)
        assert d["ANBAR_CHANNEL_ID"] == "-100123"
    finally:
        tmp_path.chmod(0o755)


def test_telegram_config_endpoint_fails_loud_when_persist_blocked(
    client: TestClient, tmp_path, monkeypatch
):
    _authed(client)
    env, fake_replace = _make_bindmount_like_env(tmp_path)
    monkeypatch.setattr(admin_mod, "_get_env_file_path", lambda: env)
    monkeypatch.setattr(os, "replace", fake_replace)

    # Tests run as root, which ignores file/dir permission bits — so instead
    # of chmod we block the in-place fallback by simulating an unwritable
    # file: monkeypatch os.open to fail with EACCES for the env path.
    real_open = os.open

    def fake_open(path, flags, *a, **kw):
        if str(path) == str(env) and flags & os.O_WRONLY:
            raise OSError(13, "Permission denied")  # EACCES
        return real_open(path, flags, *a, **kw)

    monkeypatch.setattr(os, "open", fake_open)
    r = client.post(
        "/api/v1/admin/telegram-config",
        json={"channel_id": "-100999"},
        headers=ADMIN,
    )
    assert r.status_code == 500
    assert "persist" in r.json()["detail"].lower()


def test_telegram_config_endpoint_ok_when_fallback_writes(
    client: TestClient, tmp_path, monkeypatch
):
    _authed(client)
    env, fake_replace = _make_bindmount_like_env(tmp_path)
    monkeypatch.setattr(admin_mod, "_get_env_file_path", lambda: env)
    monkeypatch.setattr(os, "replace", fake_replace)
    try:
        r = client.post(
            "/api/v1/admin/telegram-config",
            json={"channel_id": "-100777"},
            headers=ADMIN,
        )
        assert r.status_code == 200
        assert r.json()["persisted"] is True
        d = admin_mod._read_env_dict(env)
        assert d["ANBAR_CHANNEL_ID"] == "-100777"
    finally:
        tmp_path.chmod(0o755)


def test_bot_add_token_via_endpoint_and_fallback(
    client: TestClient, tmp_path, monkeypatch
):
    """The v0.15.26b add-one-token flow must persist even on a bind mount."""
    _authed(client)
    env, fake_replace = _make_bindmount_like_env(tmp_path)
    monkeypatch.setattr(admin_mod, "_get_env_file_path", lambda: env)
    monkeypatch.setattr(os, "replace", fake_replace)
    try:
        r = client.post(
            "/api/v1/admin/telegram-config",
            json={"bot_add_token": "999:NEW"},
            headers=ADMIN,
        )
        assert r.status_code == 200
        d = admin_mod._read_env_dict(env)
        toks = [t.strip() for t in d["ANBAR_BOT_TOKENS"].split(",")]
        assert toks == ["111:AAA", "999:NEW"]
    finally:
        tmp_path.chmod(0o755)


# ── 2. album TTL ─────────────────────────────────────────────────────────────
def test_album_default_ttl_24h(client: TestClient):
    _authed(client)
    o1 = _upload(client, "x1.bin", b"111111")
    o2 = _upload(client, "x2.bin", b"222222")
    r = client.post("/f/album", headers=ADMIN, json={"ids": [o1, o2]})
    assert r.status_code == 200
    token = r.json()["token"]
    page = client.get(f"/f/a/{token}")
    assert page.status_code == 200
    items = _extract_items(page.text)
    now = int(time.time())
    for it in items:
        hours = (it["exp"] - now) / 3600
        assert 23 < hours <= 24.5, f"expected ~24h exp, got {hours:.2f}h"


def test_album_ttl_zero_never_expires(client: TestClient):
    _authed(client)
    o1 = _upload(client, "n1.bin", b"abc")
    r = client.post("/f/album", headers=ADMIN, json={"ids": [o1], "ttl": 0})
    assert r.status_code == 200
    token = r.json()["token"]
    page = client.get(f"/f/a/{token}")
    assert page.status_code == 200
    items = _extract_items(page.text)
    now = int(time.time())
    for it in items:
        days = (it["exp"] - now) / 86400
        assert days > 29, f"ttl=0 must behave like the old 30-day signature, got {days:.1f}d"


def test_album_ttl_custom_value(client: TestClient):
    _authed(client)
    o1 = _upload(client, "c1.bin", b"abc")
    r = client.post("/f/album", headers=ADMIN, json={"ids": [o1], "ttl": 600})
    assert r.status_code == 200
    token = r.json()["token"]
    page = client.get(f"/f/a/{token}")
    assert page.status_code == 200
    items = _extract_items(page.text)
    now = int(time.time())
    for it in items:
        minutes = (it["exp"] - now) / 60
        assert 9 < minutes <= 11


def test_album_expired_returns_410(client: TestClient, monkeypatch):
    _authed(client)
    o1 = _upload(client, "e1.bin", b"abc")
    r = client.post("/f/album", headers=ADMIN, json={"ids": [o1], "ttl": 600})
    token = r.json()["token"]

    real_time = time.time
    monkeypatch.setattr(
        time, "time", lambda: real_time() + 700
    )
    page = client.get(f"/f/a/{token}")
    assert page.status_code == 410


def _extract_items(html: str) -> list[dict]:
    """Pull the embedded per-item dicts (id/name/sig/exp) out of the page."""
    import re

    objs = re.findall(r"\{[^{}]*\"id\"[^{}]*\"sig\"[^{}]*\}", html)
    assert objs, "no embedded items found on album page"
    return [json.loads(o) for o in objs]
