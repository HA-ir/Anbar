"""v0.9.2: per-link max download cap."""

from __future__ import annotations

import io

ADMIN = {"Authorization": "Bearer test-admin-key"}


def _upload(client, name="cap.bin", data=b"0123456789"):
    r = client.post(
        "/api/v1/upload",
        headers=ADMIN,
        files={"file": (name, io.BytesIO(data), "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    obj = j.get("object") or j
    return obj.get("id") or obj.get("object_id")


def _path(url: str) -> str:
    from urllib.parse import urlparse

    u = urlparse(url)
    return u.path + ("?" + u.query if u.query else "")


def test_maxdl_enforced(client):
    oid = _upload(client)
    r = client.post(f"/f/{oid}/link?ttl=600&max_dl=2", headers=ADMIN)
    assert r.status_code == 200 and r.json().get("max_downloads") == 2
    path = _path(r.json()["url"])
    assert client.get(path).status_code == 200  # 1st
    assert client.get(path).status_code == 200  # 2nd
    r3 = client.get(path)  # 3rd → capped
    assert r3.status_code == 410, r3.text


def test_no_cap_without_param(client):
    oid = _upload(client)
    path = _path(client.post(f"/f/{oid}/link?ttl=600", headers=ADMIN).json()["url"])
    for _ in range(5):
        assert client.get(path).status_code == 200


def test_range_not_counted(client):
    oid = _upload(client)
    r = client.post(f"/f/{oid}/link?ttl=600&max_dl=1", headers=ADMIN)
    path = _path(r.json()["url"])
    rr = client.get(path, headers={"Range": "bytes=0-3"})
    assert rr.status_code == 206  # ranges don't consume cap
    assert client.get(path).status_code == 200  # full still allowed once
