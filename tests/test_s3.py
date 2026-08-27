"""v0.11: S3 compatibility endpoints test."""

from __future__ import annotations

ADMIN = {"Authorization": "Bearer test-admin-key"}


def test_s3_crud_and_range(client):
    bucket = "mybucket"
    key = "folder/data.txt"
    payload = b"Hello S3 Compatible Anbar Storage!"

    # 1. PutObject
    r_put = client.put(
        f"/s3/{bucket}/{key}",
        headers={**ADMIN, "Content-Type": "text/plain"},
        content=payload,
    )
    assert r_put.status_code == 200
    etag = r_put.headers.get("etag")
    assert etag is not None

    # 2. HeadObject
    r_head = client.head(f"/s3/{bucket}/{key}", headers=ADMIN)
    assert r_head.status_code == 200
    assert r_head.headers.get("etag") == etag
    assert r_head.headers.get("content-length") == str(len(payload))

    # 3. GetObject full
    r_get = client.get(f"/s3/{bucket}/{key}", headers=ADMIN)
    assert r_get.status_code == 200
    assert r_get.content == payload

    # 4. GetObject conditional (304)
    r_304 = client.get(f"/s3/{bucket}/{key}", headers={**ADMIN, "If-None-Match": etag})
    assert r_304.status_code == 304

    # 5. GetObject Range
    r_range = client.get(f"/s3/{bucket}/{key}", headers={**ADMIN, "Range": "bytes=0-4"})
    assert r_range.status_code == 206
    assert r_range.content == b"Hello"
    assert r_range.headers.get("content-range") == f"bytes 0-4/{len(payload)}"

    # 6. ListObjectsV2
    r_list = client.get(f"/s3/{bucket}", headers=ADMIN)
    assert r_list.status_code == 200
    assert "ListBucketResult" in r_list.text
    assert key in r_list.text

    # 7. DeleteObject
    r_del = client.delete(f"/s3/{bucket}/{key}", headers=ADMIN)
    assert r_del.status_code == 204

    # 8. HeadObject after delete (404)
    assert client.head(f"/s3/{bucket}/{key}", headers=ADMIN).status_code == 404
