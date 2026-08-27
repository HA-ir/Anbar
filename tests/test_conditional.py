"""v0.11: conditional requests (ETag / If-None-Match -> 304) and smart media disposition."""

from __future__ import annotations

import io

ADMIN = {"Authorization": "Bearer test-admin-key"}


def _upload(
    client,
    filename="photo.png",
    data=b"\x89PNG\r\n\x1a\nfakeimage",
    content_type="image/png",
):
    r = client.post(
        "/api/v1/upload",
        headers=ADMIN,
        files={"file": (filename, io.BytesIO(data), content_type)},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"], r.json().get("sha256")


def test_etag_header_present(client):
    oid, sha = _upload(client, "test.txt", b"hello world", "text/plain")
    r = client.get(f"/f/{oid}", headers=ADMIN)
    assert r.status_code == 200
    assert "etag" in r.headers
    assert r.headers["etag"] == f'"{sha}"'


def test_if_none_match_304(client):
    oid, sha = _upload(client, "test.txt", b"hello world", "text/plain")
    # Matching ETag returns 304 Not Modified
    headers_match = {**ADMIN, "If-None-Match": f'"{sha}"'}
    r = client.get(f"/f/{oid}", headers=headers_match)
    assert r.status_code == 304
    assert r.headers.get("etag") == f'"{sha}"'
    assert len(r.content) == 0

    # Wildcard * returns 304
    headers_star = {**ADMIN, "If-None-Match": "*"}
    r_star = client.get(f"/f/{oid}", headers=headers_star)
    assert r_star.status_code == 304

    # Non-matching ETag returns 200 with full content
    headers_mismatch = {**ADMIN, "If-None-Match": '"different-hash"'}
    r_mismatch = client.get(f"/f/{oid}", headers=headers_mismatch)
    assert r_mismatch.status_code == 200
    assert r_mismatch.content == b"hello world"


def test_smart_disposition_media_vs_binary(client):
    # Image defaults to inline
    img_id, _ = _upload(client, "pic.jpg", b"imgdata", "image/jpeg")
    r_img = client.get(f"/f/{img_id}", headers=ADMIN)
    assert 'inline; filename="pic.jpg"' in r_img.headers["content-disposition"]

    # Image with ?dl=1 / ?download=1 forces attachment
    r_img_dl = client.get(f"/f/{img_id}?dl=1", headers=ADMIN)
    assert 'attachment; filename="pic.jpg"' in r_img_dl.headers["content-disposition"]

    # Binary/zip defaults to attachment
    bin_id, _ = _upload(client, "archive.zip", b"zipdata", "application/zip")
    r_bin = client.get(f"/f/{bin_id}", headers=ADMIN)
    assert 'attachment; filename="archive.zip"' in r_bin.headers["content-disposition"]

    # Binary with ?view=1 forces inline
    r_bin_view = client.get(f"/f/{bin_id}?view=1", headers=ADMIN)
    assert 'inline; filename="archive.zip"' in r_bin_view.headers["content-disposition"]
