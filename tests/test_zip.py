"""v0.10: bulk ZIP streaming download."""

from __future__ import annotations

import io
import zipfile

ADMIN = {"Authorization": "Bearer test-admin-key"}


def _upload(client, name, content):
    r = client.post(
        "/api/v1/upload",
        headers=ADMIN,
        files={"file": (name, io.BytesIO(content), "application/octet-stream")},
    )
    j = r.json()
    return (j.get("object") or j)["id"]


def test_zip_roundtrip(client):
    o1 = _upload(client, "alpha.txt", b"AAA" * 100)
    o2 = _upload(client, "beta.txt", b"BBB" * 50)
    r = client.post("/f/zip", headers=ADMIN, json={"ids": [o1, o2]})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert len(names) == 2
    assert any(n.startswith("alpha") for n in names)
    assert any(n.startswith("beta") for n in names)
    assert zf.testzip() is None
    alpha = next(zf.read(n) for n in names if n.startswith("alpha"))
    assert alpha == b"AAA" * 100


def test_zip_requires_admin(client):
    o1 = _upload(client, "a.bin", b"x")
    # uploader key may not bulk-zip
    r = client.post("/f/zip", headers={"Authorization": "Bearer test-key"}, json={"ids": [o1]})
    assert r.status_code == 403


def test_zip_empty_selection(client):
    assert client.post("/f/zip", headers=ADMIN, json={"ids": ["nonexistent00"]}).status_code == 404


def test_zip_skips_missing(client):
    o1 = _upload(client, "keep.bin", b"data")
    r = client.post("/f/zip", headers=ADMIN, json={"ids": [o1, "missing0000"]})
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert len(zf.namelist()) == 1
