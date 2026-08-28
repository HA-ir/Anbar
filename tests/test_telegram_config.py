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
    assert "bot_tokens_count" in data
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
