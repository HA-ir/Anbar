"""Tests for active Telegram Bot and MTProto credential verification."""

from __future__ import annotations

from unittest.mock import patch

from starlette.testclient import TestClient

ADMIN = {"Authorization": "Bearer test-admin-key"}


def test_telegram_test_endpoint_requires_auth(client: TestClient):
    # 1. Without credentials -> 401
    res = client.post("/api/v1/admin/telegram/test")
    assert res.status_code == 401


def test_telegram_test_endpoint_mocked_success(client: TestClient, monkeypatch, tmp_path):
    client.post("/ui/login", json={"key": "test-admin-key"})

    fake_env = tmp_path / ".env"
    fake_env.write_text("ANBAR_BOT_TOKENS=1111:AAABBB,2222:CCCDDD\n", encoding="utf-8")

    from anbar.api import admin

    monkeypatch.setattr(admin, "_get_env_file_path", lambda: fake_env)

    # Mock httpx response for bot /getMe calls
    class MockResp:
        def __init__(self, status_code: int, data: dict):
            self.status_code = status_code
            self._data = data

        def json(self):
            return self._data

    async def mock_get(url, **kwargs):
        if "1111" in url:
            bot_res = {"id": 1111, "username": "anbar_bot1", "first_name": "Bot One"}
            return MockResp(200, {"ok": True, "result": bot_res})
        return MockResp(401, {"ok": False, "description": "Unauthorized"})

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        res = client.post("/api/v1/admin/telegram/test", headers=ADMIN)
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert len(data["bots"]) == 2

        # First bot should be working
        bot1 = data["bots"][0]
        assert bot1["working"] is True
        assert bot1["username"] == "anbar_bot1"

        # Second bot should have error
        bot2 = data["bots"][1]
        assert bot2["working"] is False
        assert "Unauthorized" in bot2["error"]


def test_telegram_config_get_with_test_param(client: TestClient, monkeypatch, tmp_path):
    client.post("/ui/login", json={"key": "test-admin-key"})

    fake_env = tmp_path / ".env"
    fake_env.write_text("ANBAR_BOT_TOKENS=1111:AAABBB\n", encoding="utf-8")

    from anbar.api import admin

    monkeypatch.setattr(admin, "_get_env_file_path", lambda: fake_env)

    class MockResp:
        status_code = 200

        def json(self):
            return {"ok": True, "result": {"id": 1111, "username": "anbar_bot"}}

    with patch("httpx.AsyncClient.get", return_value=MockResp()):
        # GET with ?test=true
        res = client.get("/api/v1/admin/telegram-config?test=true", headers=ADMIN)
        assert res.status_code == 200
        data = res.json()
        assert "test_result" in data
        assert data["test_result"]["ok"] is True
        assert data["test_result"]["bots"][0]["working"] is True
