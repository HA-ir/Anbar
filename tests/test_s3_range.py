"""Repro: S3 GetObject with malformed/out-of-bounds Range must return 416 (or
200 full-body), never an unhandled 500."""

from fastapi.testclient import TestClient


def _put(client: TestClient, key="doc.txt", body=b"0123456789" * 10):
    r = client.put(
        "/s3/bucket/doc.txt",
        content=body,
        headers={"Authorization": "Bearer test-admin-key"},
    )
    assert r.status_code == 200, r.text
    return r


def test_s3_range_garbage_returns_416_not_500(client: TestClient):
    _put(client)
    r = client.get(
        "/s3/bucket/doc.txt",
        headers={"Range": "bytes=abc-def", "Authorization": "Bearer test-admin-key"},
    )
    assert r.status_code == 416, r.status_code


def test_s3_range_inverted_returns_416(client: TestClient):
    _put(client)
    r = client.get(
        "/s3/bucket/doc.txt",
        headers={"Range": "bytes=5-2", "Authorization": "Bearer test-admin-key"},
    )
    assert r.status_code == 416


def test_s3_range_out_of_bounds_returns_416(client: TestClient):
    _put(client)
    r = client.get(
        "/s3/bucket/doc.txt",
        headers={"Range": "bytes=150-", "Authorization": "Bearer test-admin-key"},
    )
    assert r.status_code == 416


def test_s3_range_end_clamped_to_total(client: TestClient):
    _put(client)
    r = client.get(
        "/s3/bucket/doc.txt",
        headers={"Range": "bytes=0-99999999999999999999", "Authorization": "Bearer test-admin-key"},
    )
    assert r.status_code == 206
    assert r.headers["content-range"] == "bytes 0-99/100"


def test_s3_valid_range_still_works(client: TestClient):
    _put(client)
    r = client.get(
        "/s3/bucket/doc.txt",
        headers={"Range": "bytes=0-9", "Authorization": "Bearer test-admin-key"},
    )
    assert r.status_code == 206
    assert r.content == b"0123456789"
