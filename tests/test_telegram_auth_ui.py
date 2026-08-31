from fastapi.testclient import TestClient


def test_telegram_auth_endpoints_exist(client: TestClient):
    """Test send-code and verify-code endpoints validation with admin key."""
    headers = {"Authorization": "Bearer test-admin-key"}

    # 1. Missing phone
    r1 = client.post("/api/v1/admin/telegram/send-code", json={}, headers=headers)
    assert r1.status_code == 400

    # 2. Missing verification params
    r2 = client.post("/api/v1/admin/telegram/verify-code", json={}, headers=headers)
    assert r2.status_code == 400
