"""v0.10: share-link registry (list/revoke) + trash (soft delete/restore/purge)."""
from __future__ import annotations

import io

ADMIN = {"Authorization": "Bearer test-admin-key"}


def _upload(client, name="f.bin", content=b"data"):
    r = client.post("/api/v1/upload", headers=ADMIN,
                    files={"file": (name, io.BytesIO(content), "application/octet-stream")})
    j = r.json()
    return j.get("object") or j


def test_link_registered_and_listed(client):
    oid = _upload(client)["id"]
    client.post(f"/f/{oid}/link?ttl=3600&slug=lnk", headers=ADMIN)
    links = client.get("/api/v1/admin/links", headers=ADMIN).json()["links"]
    assert len(links) == 1
    row = links[0]
    assert row["obj_id"] == oid and row["slug"] == "lnk"
    assert row["expired"] is False and row["revoked"] is False
    assert row["filename"] == "f.bin"


def test_revoke_kills_link(client):
    oid = _upload(client)["id"]
    url = client.post(f"/f/{oid}/link?ttl=600", headers=ADMIN).json()["url"]
    import urllib.parse
    u = urllib.parse.urlparse(url)
    assert client.get(u.path + "?" + u.query).status_code == 200
    exp = int(u.query.split("exp=")[1])
    r = client.post(f"/api/v1/admin/links/{oid}/revoke/{exp}", headers=ADMIN)
    assert r.status_code == 200
    # same URL now returns 410 revoked
    assert client.get(u.path + "?" + u.query).status_code == 410
    # listing shows revoked state
    links = client.get("/api/v1/admin/links", headers=ADMIN).json()["links"]
    assert links[0]["revoked"] is True
    # revoking again → 404 (already gone)
    assert client.post(f"/api/v1/admin/links/{oid}/revoke/{exp}",
                       headers=ADMIN).status_code == 404


def test_soft_delete_hides_then_restore(client):
    o = _upload(client)
    oid = o["id"]
    # visible in list
    ids = [x["id"] for x in client.get("/api/v1/admin/objects",
                                       headers=ADMIN).json()["objects"]]
    assert oid in ids
    # delete → trashed
    r = client.delete(f"/f/{oid}", headers=ADMIN).json()
    assert r["trashed"] is True
    # gone from normal list + download 404
    ids = [x["id"] for x in client.get("/api/v1/admin/objects",
                                       headers=ADMIN).json()["objects"]]
    assert oid not in ids
    assert client.get(f"/f/{oid}", headers=ADMIN).status_code == 404
    # in trash with a purge window
    trash = client.get("/api/v1/admin/trash", headers=ADMIN).json()
    assert any(i["id"] == oid for i in trash["items"])
    item = next(i for i in trash["items"] if i["id"] == oid)
    assert item["purge_in_s"] > 0
    # restore brings it back
    r = client.post(f"/api/v1/admin/trash/{oid}/restore", headers=ADMIN)
    assert r.status_code == 200
    ids = [x["id"] for x in client.get("/api/v1/admin/objects",
                                       headers=ADMIN).json()["objects"]]
    assert oid in ids


def test_purge_destroys_for_real(client):
    o = _upload(client)
    oid = o["id"]
    client.delete(f"/f/{oid}", headers=ADMIN)
    r = client.delete(f"/f/{oid}?purge=true", headers=ADMIN).json()
    assert r["purged"] is True
    # not restorable anymore
    assert client.post(f"/api/v1/admin/trash/{oid}/restore",
                       headers=ADMIN).status_code == 404
    db = client.app.state.db
    assert db.get_object(oid, include_trashed=True) is None


def test_trash_purge_one_endpoint(client):
    o = _upload(client)
    oid = o["id"]
    client.delete(f"/f/{oid}", headers=ADMIN)
    r = client.delete(f"/api/v1/admin/trash/{oid}", headers=ADMIN)
    assert r.status_code == 200
    assert r.json()["purged"] == oid
