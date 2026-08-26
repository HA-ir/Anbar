"""v0.9: rename endpoint + pw cleanup on delete."""

from __future__ import annotations

import io

ADMIN = {"Authorization": "Bearer test-admin-key"}


def _upload(client, name="old.bin"):
    r = client.post(
        "/api/v1/upload",
        headers=ADMIN,
        files={"file": (name, io.BytesIO(b"data"), "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    obj = j.get("object") or j
    return obj.get("id") or obj.get("object_id")


def test_rename_roundtrip(client):
    oid = _upload(client)
    r = client.patch(f"/f/{oid}", json={"filename": "new name.bin"}, headers=ADMIN)
    assert r.status_code == 200, r.text
    assert r.json()["filename"] == "new name.bin"
    # visible in listing
    lst = client.get("/api/v1/admin/objects", headers=ADMIN).json()["objects"]
    assert any(o["id"] == oid and o["filename"] == "new name.bin" for o in lst)


def test_rename_validation(client):
    oid = _upload(client)
    for bad in ("", "a/b", "a\\b", "x" * 201):
        r = client.patch(f"/f/{oid}", json={"filename": bad}, headers=ADMIN)
        assert r.status_code == 400, bad
    # unknown object
    r = client.patch("/f/nonexistent00", json={"filename": "ok"}, headers=ADMIN)
    assert r.status_code == 404


def test_delete_clears_pw_tag(client):
    oid = _upload(client)
    client.post(f"/f/{oid}/link?ttl=600&password=pp", headers=ADMIN)
    # confirm protected
    from urllib.parse import urlparse

    u = urlparse(client.post(f"/f/{oid}/link?ttl=600", headers=ADMIN).json()["url"])
    assert client.get(u.path + "?" + u.query).status_code == 403
    # delete → v0.10 trashes the object; purge destroys it for real
    client.delete(f"/f/{oid}", headers=ADMIN)
    # kv tag must be gone after purge
    client.delete(f"/f/{oid}?purge=true", headers=ADMIN)
    db = client.app.state.db
    assert db.kv_get(f"pw:{oid}") is None
