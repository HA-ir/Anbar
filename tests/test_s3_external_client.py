"""Tests for External S3 Client Compatibility (SigV4, SigV2, Multi-Delete)."""

from __future__ import annotations

from starlette.testclient import TestClient

ADMIN_KEY = "test-admin-key"
SIGV4_HEADER = {
    "Authorization": (
        f"AWS4-HMAC-SHA256 Credential={ADMIN_KEY}/20261009/us-east-1/s3/aws4_request, "
        "SignedHeaders=host;x-amz-date, Signature=abcdef1234567890"
    ),
    "x-amz-date": "20261009T120000Z",
}
SIGV2_HEADER = {
    "Authorization": f"AWS {ADMIN_KEY}:mockSignature123=",
    "Date": "Fri, 09 Oct 2026 12:00:00 GMT",
}


def test_s3_external_sigv4_auth_and_crud(client: TestClient):
    """External S3 client sending SigV4 headers authenticates and manages objects."""
    bucket = "backup"
    key = "daily/report.pdf"
    content = b"%PDF-1.4 mock pdf content for S3 testing"

    # 1. PutObject with SigV4 Authorization header
    r_put = client.put(
        f"/s3/{bucket}/{key}",
        headers={**SIGV4_HEADER, "Content-Type": "application/pdf"},
        content=content,
    )
    assert r_put.status_code == 200, f"PutObject failed: {r_put.text}"
    etag = r_put.headers.get("etag")
    assert etag is not None

    # 2. HeadObject with SigV4
    r_head = client.head(f"/s3/{bucket}/{key}", headers=SIGV4_HEADER)
    assert r_head.status_code == 200
    assert r_head.headers.get("etag") == etag
    assert r_head.headers.get("content-length") == str(len(content))

    # 3. GetObject with SigV4
    r_get = client.get(f"/s3/{bucket}/{key}", headers=SIGV4_HEADER)
    assert r_get.status_code == 200
    assert r_get.content == content

    # 4. GetObject with Range using SigV4
    r_range = client.get(f"/s3/{bucket}/{key}", headers={**SIGV4_HEADER, "Range": "bytes=0-3"})
    assert r_range.status_code == 206
    assert r_range.content == b"%PDF"


def test_s3_external_sigv2_and_presigned_url(client: TestClient):
    """External S3 client using AWS SigV2 or presigned URL query parameter."""
    bucket = "media"
    key = "track.mp3"
    content = b"ID3\x03\x00\x00\x00 mock audio"

    # PutObject with SigV2
    r_put = client.put(f"/s3/{bucket}/{key}", headers=SIGV2_HEADER, content=content)
    assert r_put.status_code == 200

    # GetObject via Presigned URL query param (?X-Amz-Credential=...)
    qs = f"X-Amz-Credential={ADMIN_KEY}%2F20261009%2Fus-east-1%2Fs3%2Faws4_request"
    presigned = f"/s3/{bucket}/{key}?{qs}"
    r_get = client.get(presigned)
    assert r_get.status_code == 200
    assert r_get.content == content


def test_s3_multi_object_delete(client: TestClient):
    """External S3 client performing multi-object delete (POST /s3/{bucket}?delete)."""
    bucket = "warehouse"
    # Seed 3 objects
    client.put(f"/s3/{bucket}/item1.txt", headers=SIGV4_HEADER, content=b"item1")
    client.put(f"/s3/{bucket}/item2.txt", headers=SIGV4_HEADER, content=b"item2")
    client.put(f"/s3/{bucket}/item3.txt", headers=SIGV4_HEADER, content=b"item3")

    delete_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Delete>
    <Quiet>false</Quiet>
    <Object><Key>item1.txt</Key></Object>
    <Object><Key>item2.txt</Key></Object>
</Delete>"""

    # Multi-delete call
    r_del = client.post(
        f"/s3/{bucket}?delete",
        headers={**SIGV4_HEADER, "Content-Type": "application/xml"},
        content=delete_xml.encode("utf-8"),
    )
    assert r_del.status_code == 200, f"DeleteObjects failed: {r_del.text}"
    assert "DeleteResult" in r_del.text
    assert "<Key>item1.txt</Key>" in r_del.text
    assert "<Key>item2.txt</Key>" in r_del.text

    # Verify deleted items return 404, kept item returns 200
    assert client.head(f"/s3/{bucket}/item1.txt", headers=SIGV4_HEADER).status_code == 404
    assert client.head(f"/s3/{bucket}/item2.txt", headers=SIGV4_HEADER).status_code == 404
    assert client.head(f"/s3/{bucket}/item3.txt", headers=SIGV4_HEADER).status_code == 200


def test_s3_trailing_slash_endpoints(client: TestClient):
    """External S3 clients requesting trailing-slash endpoints (/s3/bucket/ and /s3/)."""
    # 1. ListBuckets with trailing slash
    r1 = client.get("/s3/", headers=SIGV4_HEADER)
    assert r1.status_code == 200
    assert "ListAllMyBucketsResult" in r1.text

    # 2. HeadBucket with trailing slash
    r2 = client.head("/s3/default/", headers=SIGV4_HEADER)
    assert r2.status_code == 200

    # 3. ListObjects with trailing slash
    r3 = client.get("/s3/default/", headers=SIGV4_HEADER)
    assert r3.status_code == 200
    assert "ListBucketResult" in r3.text


def test_s3_xxe_and_doctype_rejection(client: TestClient):
    """S3 DeleteObjects strictly rejects DOCTYPE and ENTITY injections."""
    malicious_xml = """<?xml version="1.0"?>
    <!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
    <Delete><Object><Key>&xxe;</Key></Object></Delete>"""

    r = client.post(
        "/s3/testbucket?delete",
        headers={**SIGV4_HEADER, "Content-Type": "application/xml"},
        content=malicious_xml.encode("utf-8"),
    )
    assert r.status_code == 400
    assert "MalformedXML" in r.text


def test_s3_dynamic_uploader_key_auth(client: TestClient):
    """Dynamic API keys issued in admin panel authenticate external S3 clients."""
    # Create dynamic key via admin
    r_create = client.post(
        "/api/v1/admin/api-keys",
        headers={"Authorization": f"Bearer {ADMIN_KEY}"},
        json={"name": "s3-backup-agent"},
    )
    assert r_create.status_code == 200
    dynamic_key = r_create.json()["key"]

    dynamic_sigv4 = {
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={dynamic_key}/20261009/us-east-1/s3/aws4_request, "
            "SignedHeaders=host;x-amz-date, Signature=dummy"
        ),
    }

    # Put and Get with dynamic key
    r_put = client.put("/s3/dyn/file.txt", headers=dynamic_sigv4, content=b"dynamic key s3 content")
    assert r_put.status_code == 200

    r_get = client.get("/s3/dyn/file.txt", headers=dynamic_sigv4)
    assert r_get.status_code == 200
    assert r_get.content == b"dynamic key s3 content"
