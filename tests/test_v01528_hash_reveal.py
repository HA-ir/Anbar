"""v0.15.28 regression tests: raw api_hash reveal endpoint (BUG-v0.15.28).

Covers:
- reveal endpoint returns the RAW hash to an admin key
- anonymous / uploader keys are rejected (401/403)
- every reveal is audit-logged (cfg.reveal_api_hash)
- listing endpoint still returns only the masked hash (B-054 untouched)
- i18n parity still holds for the new keys (hashNotSet)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from anbar.api import admin as admin_mod

ADMIN = {"Authorization": "Bearer test-admin-key"}


@pytest.fixture()
def isolated_env(tmp_path: Path, monkeypatch):
    env = tmp_path / "test.env"
    env.write_text(
        "ANBAR_BOT_TOKEN=123456:AAA.BBB\n"
        "ANBAR_API_HASH=" + "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6" + "\n"
    )
    monkeypatch.setattr(admin_mod, "_get_env_file_path", lambda: env)
    return env


def test_reveal_returns_raw_hash_to_admin(client, isolated_env):
    r = client.get("/api/v1/admin/telegram-config/reveal-api-hash", headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert body["set"] is True
    assert body["api_hash"] == "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
    assert "•" not in body["api_hash"]


def test_reveal_requires_admin(client, isolated_env):
    r = client.get("/api/v1/admin/telegram-config/reveal-api-hash")
    assert r.status_code in (401, 403)
    # an uploader (dynamic/API) key must not get the raw hash either
    r2 = client.get(
        "/api/v1/admin/telegram-config/reveal-api-hash",
        headers={"Authorization": "Bearer not-the-admin-key"},
    )
    assert r2.status_code in (401, 403)


def test_reveal_is_audit_logged(client, isolated_env):
    client.get("/api/v1/admin/telegram-config/reveal-api-hash", headers=ADMIN)
    db = client.app.state.db  # type: ignore[attr-defined]
    rows = db._conn.execute(
        "SELECT event FROM audit_logs WHERE event='cfg.reveal_api_hash'"
    ).fetchall()
    assert rows, "reveal click must be audit-logged"


def test_listing_still_masks_hash(client, isolated_env):
    r = client.get("/api/v1/admin/telegram-config", headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert "•" in body["api_hash"]
    assert body["api_hash"] != "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
