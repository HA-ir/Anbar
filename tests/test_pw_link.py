"""v0.9: password-protected share links + ingest notification wiring."""
from __future__ import annotations

ADMIN = {"Authorization": "Bearer test-admin-key"}


def _upload(client, name="pw.bin", data=b"hello protected"):
    import io

    r = client.post("/api/v1/upload", headers=ADMIN,
                    files={"file": (name, io.BytesIO(data), "application/octet-stream")})
    assert r.status_code == 200, r.text
    j = r.json()
    obj = j.get("object") or j
    oid = obj.get("id") or obj.get("object_id")
    assert oid, j
    return oid


def test_password_link_roundtrip(client):
    from urllib.parse import urlparse

    oid = _upload(client)
    r = client.post(f"/f/{oid}/link?ttl=3600&password=s3cret", headers=ADMIN)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("password_protected") is True
    url = j["url"]

    path = urlparse(url).path + "?" + urlparse(url).query

    # without pw → 403
    assert client.get(path).status_code == 403
    # wrong pw → 403
    assert client.get(path + "&pw=wrong").status_code == 403
    # correct pw → 200
    assert client.get(path + "&pw=s3cret").status_code == 200


def test_plain_link_unaffected(client):
    from urllib.parse import urlparse

    oid = _upload(client, "plain.bin")
    r = client.post(f"/f/{oid}/link?ttl=3600", headers=ADMIN)
    assert r.status_code == 200
    assert "password_protected" not in r.json()
    u = urlparse(r.json()["url"])
    assert client.get(u.path + "?" + u.query).status_code == 200
