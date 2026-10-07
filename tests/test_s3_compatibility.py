"""Tests for S3 protocol compatibility: ListBuckets, HeadBucket, CreateBucket, prefix/delimiter."""

from __future__ import annotations

from starlette.testclient import TestClient

ADMIN = {"Authorization": "Bearer test-admin-key"}


def test_s3_list_buckets(client: TestClient):
    client.post("/ui/login", json={"key": "test-admin-key"})
    # Put an object in a custom bucket
    client.put("/s3/finance/ledger.csv", headers=ADMIN, content=b"date,amount\n2026,100")

    # 1. GET /s3
    r = client.get("/s3", headers=ADMIN)
    assert r.status_code == 200
    assert "ListAllMyBucketsResult" in r.text
    assert "<Name>finance</Name>" in r.text
    assert "<Name>default</Name>" in r.text

    # 2. GET /s3/
    r2 = client.get("/s3/", headers=ADMIN)
    assert r2.status_code == 200
    assert "ListAllMyBucketsResult" in r2.text


def test_s3_head_and_create_bucket(client: TestClient):
    client.post("/ui/login", json={"key": "test-admin-key"})

    # 1. HEAD /s3/mybucket
    r_head = client.head("/s3/mybucket", headers=ADMIN)
    assert r_head.status_code == 200
    assert r_head.headers.get("x-amz-bucket-region") == "us-east-1"

    # 2. PUT /s3/mybucket (CreateBucket)
    r_put = client.put("/s3/mybucket", headers=ADMIN)
    assert r_put.status_code == 200
    assert "/s3/mybucket" in r_put.headers.get("location", "")


def test_s3_prefix_and_delimiter_common_prefixes(client: TestClient):
    client.post("/ui/login", json={"key": "test-admin-key"})
    bucket = "docs"

    # Put objects:
    # docs/readme.txt
    # docs/images/pic1.png
    # docs/images/pic2.png
    # docs/images/sub/deep.png
    client.put(f"/s3/{bucket}/readme.txt", headers=ADMIN, content=b"readme")
    client.put(f"/s3/{bucket}/images/pic1.png", headers=ADMIN, content=b"png1")
    client.put(f"/s3/{bucket}/images/pic2.png", headers=ADMIN, content=b"png2")
    client.put(f"/s3/{bucket}/images/sub/deep.png", headers=ADMIN, content=b"deep")

    # 1. Query root with delimiter=/
    # Expected: Contents has readme.txt, CommonPrefixes has images/
    r_root = client.get(f"/s3/{bucket}?delimiter=/", headers=ADMIN)
    assert r_root.status_code == 200
    assert "<Key>readme.txt</Key>" in r_root.text
    assert "<CommonPrefixes><Prefix>images/</Prefix></CommonPrefixes>" in r_root.text
    assert "<Key>images/pic1.png</Key>" not in r_root.text

    # 2. Query prefix=images/ with delimiter=/
    # Expected: Contents has images/pic1.png and images/pic2.png, CommonPrefixes has images/sub/
    r_sub = client.get(f"/s3/{bucket}?prefix=images/&delimiter=/", headers=ADMIN)
    assert r_sub.status_code == 200
    assert "<Key>images/pic1.png</Key>" in r_sub.text
    assert "<Key>images/pic2.png</Key>" in r_sub.text
    assert "<CommonPrefixes><Prefix>images/sub/</Prefix></CommonPrefixes>" in r_sub.text
    assert "<Key>images/sub/deep.png</Key>" not in r_sub.text
