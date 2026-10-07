from starlette.testclient import TestClient

ADMIN = {"Authorization": "Bearer test-admin-key"}


def _authed(client):
    client.post("/ui/login", json={"key": "test-admin-key"})


def test_telegram_config_get(client: TestClient):
    _authed(client)
    r = client.get("/api/v1/admin/telegram-config", headers=ADMIN)
    assert r.status_code == 200
    data = r.json()
    assert "backend" in data
    # B-054: raw token fields are gone; count moved into the masked block
    assert "bot_tokens_raw" not in data
    assert data.get("bot_tokens_count") is not None or "bot_tokens_masked" in data
    assert "channel_id" in data
    assert "api_id" in data


def test_telegram_config_update(client: TestClient, tmp_path, monkeypatch):
    _authed(client)
    fake_env = tmp_path / ".env"
    fake_env.write_text("ANBAR_BACKEND=bot\nANBAR_CHANNEL_ID=-100111222\n", encoding="utf-8")

    from anbar.api import admin

    monkeypatch.setattr(admin, "_get_env_file_path", lambda: fake_env)

    token1 = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    token2 = "987654:XYZ-ABC1234ghIkl-zyx57W2v1u123ew22"
    payload = {
        "backend": "mtproto",
        "bot_tokens": f"{token1},{token2}",
        "channel_id": "-100999888777",
        "api_id": "12345678",
        "api_hash": "abcdef0123456789abcdef0123456789",
        "mtproto_peer": "-100999888777",
        "chunk_size_mb": 20,
    }
    r = client.post("/api/v1/admin/telegram-config", json=payload, headers=ADMIN)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    env_dict = admin._read_env_dict(fake_env)
    assert env_dict["ANBAR_BACKEND"] == "mtproto"
    assert env_dict["ANBAR_CHANNEL_ID"] == "-100999888777"
    assert env_dict["ANBAR_API_ID"] == "12345678"
    assert env_dict["ANBAR_CHUNK_SIZE_MB"] == "20"


def test_telegram_config_hybrid(client: TestClient, tmp_path, monkeypatch):
    _authed(client)
    fake_env = tmp_path / ".env"
    fake_env.write_text("ANBAR_BACKEND=bot\n", encoding="utf-8")

    from anbar.api import admin

    monkeypatch.setattr(admin, "_get_env_file_path", lambda: fake_env)

    payload = {"backend": "hybrid"}
    r = client.post("/api/v1/admin/telegram-config", json=payload, headers=ADMIN)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    env_dict = admin._read_env_dict(fake_env)
    assert env_dict["ANBAR_BACKEND"] == "mtproto"
    assert env_dict["ANBAR_HYBRID_ENABLED"] == "true"


def test_telegram_config_validation(client: TestClient):
    _authed(client)
    r = client.post(
        "/api/v1/admin/telegram-config",
        json={"backend": "invalid_backend"},
        headers=ADMIN,
    )
    assert r.status_code == 422

    r = client.post(
        "/api/v1/admin/telegram-config",
        json={"api_id": "not_a_number"},
        headers=ADMIN,
    )
    assert r.status_code == 422

    r = client.post(
        "/api/v1/admin/telegram-config",
        json={"chunk_size_mb": 999},
        headers=ADMIN,
    )
    assert r.status_code == 422


def test_telegram_config_webhook_and_owner_ids(client: TestClient, tmp_path, monkeypatch):
    _authed(client)
    fake_env = tmp_path / ".env"
    fake_env.write_text("ANBAR_BACKEND=bot\n", encoding="utf-8")

    from unittest.mock import patch

    from anbar.api import admin

    monkeypatch.setattr(admin, "_get_env_file_path", lambda: fake_env)

    # 1. Update owner_tg_ids and tg_webhook_secret
    payload = {
        "owner_tg_ids": "12345678, 87654321",
        "tg_webhook_secret": "my-secret-token-xyz",
    }
    r = client.post("/api/v1/admin/telegram-config", json=payload, headers=ADMIN)
    assert r.status_code == 200
    env_dict = admin._read_env_dict(fake_env)
    assert env_dict["ANBAR_OWNER_TG_IDS"] == "12345678, 87654321"
    assert env_dict["ANBAR_TG_WEBHOOK_SECRET"] == "my-secret-token-xyz"

    # 2. Get config returns owner_tg_ids and masked webhook secret
    r_get = client.get("/api/v1/admin/telegram-config", headers=ADMIN)
    assert r_get.status_code == 200
    data = r_get.json()
    assert data["owner_tg_ids"] == "12345678, 87654321"
    assert "•" in data["tg_webhook_secret"]

    # 3. Test admin webhook set, info, delete endpoints
    s = client.app.state.settings  # type: ignore[attr-defined]
    s.bot_tokens_raw = "123456:FAKE_TOKEN"

    from unittest.mock import MagicMock

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "ok": True,
        "description": "Webhook set",
        "result": {"url": "https://example.com/api/v1/tg/webhook"},
    }

    class MockAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            return mock_resp

        async def get(self, *args, **kwargs):
            return mock_resp

    with patch("httpx.AsyncClient", return_value=MockAsyncClient()):
        r_set = client.post(
            "/api/v1/admin/telegram/webhook/set",
            json={"url": "https://example.com/api/v1/tg/webhook"},
            headers=ADMIN,
        )
        assert r_set.status_code == 200
        assert r_set.json()["status"] == "ok"

        r_info = client.get("/api/v1/admin/telegram/webhook/info", headers=ADMIN)
        assert r_info.status_code == 200
        assert r_info.json()["url"] == "https://example.com/api/v1/tg/webhook"

        r_del = client.post("/api/v1/admin/telegram/webhook/delete", headers=ADMIN)
        assert r_del.status_code == 200
        assert r_del.json()["status"] == "ok"
