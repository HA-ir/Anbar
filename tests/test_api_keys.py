"""Dynamic API keys: create → use → list (masked) → revoke."""

from __future__ import annotations

ADMIN = {"Authorization": "Bearer test-admin-key"}


def _post(client, path, body=None):
    return client.post(path, json=body or {}, headers=ADMIN)


def test_api_key_lifecycle(client):
    # empty at start
    r = client.get("/api/v1/admin/api-keys", headers=ADMIN)
    assert r.status_code == 200 and r.json()["keys"] == []

    # create
    r = _post(client, "/api/v1/admin/api-keys", {"name": "ci-bot"})
    assert r.status_code == 200
    data = r.json()
    key, kid = data["key"], data["id"]
    assert key and len(key) > 20

    # the new key authenticates as uploader on a real endpoint
    r = client.get("/ui/me", headers={"Authorization": f"Bearer {key}"})
    assert r.json() == {"authed": True, "role": "uploader"}

    # listing masks the key material
    r = client.get("/api/v1/admin/api-keys", headers=ADMIN)
    keys = r.json()["keys"]
    assert len(keys) == 1 and "key" not in keys[0] and keys[0]["name"] == "ci-bot"

    # revoke
    r = client.delete(f"/api/v1/admin/api-keys/{kid}", headers=ADMIN)
    assert r.status_code == 200
    r = client.get("/ui/me", headers={"Authorization": f"Bearer {key}"})
    assert r.json()["role"] == "anon"

    # revoking again → 404
    r = client.delete(f"/api/v1/admin/api-keys/{kid}", headers=ADMIN)
    assert r.status_code == 404


def test_api_key_endpoints_require_admin(client):
    r = client.get("/api/v1/admin/api-keys")
    assert r.status_code == 401
