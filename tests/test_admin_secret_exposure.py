"""Loop #7 audit tests (B-054: no raw secrets in telegram-config response).

These tests MUST run with the prod env path neutralised: _get_env_file_path()
prefers /opt/anbar/.env when it exists, so on a deploy host the test would
otherwise read/write the real environment file. We monkeypatch it to a tmp
path before touching the endpoint.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from anbar.api import admin as admin_mod

ADMIN = {"Authorization": "Bearer test-admin-key"}


@pytest.fixture()
def isolated_env(tmp_path: Path, monkeypatch):
    """Point the telegram-config endpoint at a throwaway .env file."""
    env = tmp_path / "test.env"
    env.write_text(
        "ANBAR_BOT_TOKEN=123456:AAA.BBB\n"
        "ANBAR_API_HASH=" + "d" * 32 + "\n"
        "ANBAR_CHANNEL_ID=-100orig\n"
    )
    monkeypatch.setattr(admin_mod, "_get_env_file_path", lambda: env)
    return env


def test_telegram_config_never_returns_raw_tokens(client, isolated_env):
    """B-054: GET telegram-config must return masked tokens only."""
    r = client.get("/api/v1/admin/telegram-config", headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    # the old leaking key must not exist at all
    assert "bot_tokens_raw" not in body
    # masked tokens must never be a full token shape
    for t in body.get("bot_tokens_masked", []):
        assert "•" in t or t == "****"
    # api_hash must be masked, not raw
    if body.get("api_hash"):
        assert "•" in body["api_hash"]


def test_telegram_config_empty_update_keeps_secrets(client, isolated_env):
    """B-054 companion: posting no token/hash fields must not wipe the .env."""
    r = client.post(
        "/api/v1/admin/telegram-config",
        headers=ADMIN,
        json={"channel_id": "-100new"},
    )
    assert r.status_code == 200
    text = isolated_env.read_text()
    assert "123456:AAA.BBB" in text, "token-less update wiped the stored token"
    assert "dddddddd" in text, "hash-less update wiped the stored hash"
    assert "ANBAR_CHANNEL_ID=-100new" in text


def test_telegram_config_env_with_garbage_chunk_size(client, isolated_env):
    """B-055: a non-numeric ANBAR_CHUNK_SIZE_MB row must not 500 the endpoint."""
    isolated_env.write_text("ANBAR_CHUNK_SIZE_MB=not-a-number\n")
    r = client.get("/api/v1/admin/telegram-config", headers=ADMIN)
    assert r.status_code == 200
    assert isinstance(r.json()["chunk_size_mb"], int)
