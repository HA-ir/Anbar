"""Comprehensive tests for Wave 1 hardening (SEC-B1 through SEC-B9 and REL-C1 through REL-C4)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from anbar.api.ingest import validate_url_target
from anbar.auth import hash_key, list_api_keys
from anbar.db import Database
from anbar.tasks import _BACKGROUND_TASKS, spawn_background_task

ADMIN = {"Authorization": "Bearer test-admin-key"}
UP = {"Authorization": "Bearer test-key"}


def test_sec_b1_admin_secret_masked(client: TestClient):
    """SEC-B1: GET /admin/auth/secret and rotate-secret must never leak raw secret."""
    # 1. GET secret must return masked representation
    r = client.get("/api/v1/admin/auth/secret", headers=ADMIN)
    assert r.status_code == 200
    data = r.json()
    assert "secret" not in data
    assert data.get("configured") is True
    assert "..." in data.get("masked", "") or "*" in data.get("masked", "")

    # 2. Rotate secret must not echo raw secret
    r_rot = client.post("/api/v1/admin/auth/rotate-secret", json={}, headers=ADMIN)
    assert r_rot.status_code == 200
    data_rot = r_rot.json()
    assert "hmac_secret" not in data_rot
    assert data_rot.get("status") == "rotated"
    assert "..." in data_rot.get("masked", "") or "*" in data_rot.get("masked", "")


def test_sec_b2_password_check_enforced_when_auth_off(client: TestClient):
    """SEC-B2: Password-protected objects must still require password when auth is OFF."""
    # Upload an object
    r_up = client.post(
        "/api/v1/upload",
        files={"file": ("secret_doc.txt", b"top-secret-content", "text/plain")},
        headers=ADMIN,
    )
    assert r_up.status_code == 200
    obj_id = r_up.json()["id"]

    # Mint link with password protection
    r_pw = client.post(
        f"/f/{obj_id}/link?password=mypassword123",
        headers=ADMIN,
    )
    assert r_pw.status_code == 200

    # Turn auth OFF globally
    r_toggle = client.post("/api/v1/admin/auth/toggle", headers=ADMIN)
    assert r_toggle.status_code == 200
    assert r_toggle.json()["auth_enabled"] is False

    try:
        # Anonymous access without password must be 403 password required
        r_anon = client.get(f"/f/{obj_id}")
        assert r_anon.status_code == 403

        # Anonymous info endpoint without password must also be 403
        r_info = client.get(f"/f/{obj_id}/info")
        assert r_info.status_code == 403

        # Anonymous access with wrong password must be 403
        r_wrong = client.get(f"/f/{obj_id}?pw=wrongpass")
        assert r_wrong.status_code == 403

        # Anonymous access with correct password must succeed
        r_ok = client.get(f"/f/{obj_id}?pw=mypassword123")
        assert r_ok.status_code == 200
        assert r_ok.content == b"top-secret-content"
    finally:
        # Turn auth back ON
        client.post("/api/v1/admin/auth/toggle", headers=ADMIN)


def test_sec_b3_s3_anonymous_writes_rejected_when_auth_off(client: TestClient):
    """SEC-B3: Even when global auth is OFF, anonymous S3 writes must be rejected."""
    # Turn auth OFF
    client.post("/api/v1/admin/auth/toggle", headers=ADMIN)
    try:
        # Anonymous S3 PUT must fail with 401
        r_put = client.put("/s3/testbucket/file.txt", content=b"hello")
        assert r_put.status_code == 401

        # Anonymous S3 DELETE must fail with 401
        r_del = client.delete("/s3/testbucket/file.txt")
        assert r_del.status_code == 401

        # Authed S3 PUT still succeeds
        r_put_auth = client.put(
            "/s3/testbucket/file.txt",
            headers=ADMIN,
            content=b"hello",
        )
        assert r_put_auth.status_code == 200
    finally:
        client.post("/api/v1/admin/auth/toggle", headers=ADMIN)


def test_sec_b3_s3_default_bucket_isolation(client: TestClient):
    """SEC-B3: GET /s3/default must not leak objects stored under other bucket prefixes."""
    # Put an object in custombucket
    client.put("/s3/custombucket/private.txt", headers=ADMIN, content=b"private")
    # Put an object in default bucket
    client.put("/s3/default/public.txt", headers=ADMIN, content=b"public")

    r_list = client.get("/s3/default", headers=ADMIN)
    assert r_list.status_code == 200
    assert "public.txt" in r_list.text
    assert "private.txt" not in r_list.text


def test_sec_b3_and_rel_c3_s3_list_pagination(client: TestClient):
    """SEC-B3: every object appears across paginated lists, not just the first 1,000."""
    client.post("/api/v1/admin/settings", headers=ADMIN, json={"rate_upload": 100000})
    payloads = [
        client.put(f"/s3/paged/obj-{number:04d}.txt", headers=ADMIN, content=b"x").status_code
        for number in range(1001)
    ]
    assert set(payloads) == {200}

    seen = []
    token = None
    for _ in range(3):
        params = {"max-keys": 500}
        if token:
            params["continuation-token"] = token
        response = client.get("/s3/paged", headers=ADMIN, params=params)
        assert response.status_code == 200
        seen.append(response.text.count("obj-"))
        if "<NextContinuationToken>" in response.text:
            token = response.text.split("<NextContinuationToken>")[1].split("</")[0]
        else:
            token = None
    assert seen == [500, 500, 1]


def test_sec_b4_upload_running_byte_ceiling_exceeded(client: TestClient):
    """SEC-B4: Streaming upload exceeding max_upload_mb must abort with 413 even if unannounced."""
    db = client.app.state.db
    from anbar import runtime

    # Set max_upload_mb to 1MB temporarily via runtime
    runtime.set_int(db, "max_upload_mb", 1)
    try:
        # Send > 1MB (e.g. 1.2MB) without Content-Length or with chunked streaming
        oversized = b"X" * (1024 * 1024 + 50 * 1024)
        r = client.post(
            "/api/v1/upload/raw",
            content=oversized,
            headers={**ADMIN, "X-File-Name": "large.bin"},
        )
        assert r.status_code == 413
    finally:
        runtime.reset(db, "max_upload_mb")


def test_sec_b5_api_keys_hashed_in_kv(client: TestClient):
    """SEC-B5: API keys stored in database must be hashed, never plaintext."""
    db = client.app.state.db
    r_create = client.post("/api/v1/admin/api-keys", json={"name": "test-key-b5"}, headers=ADMIN)
    assert r_create.status_code == 200
    data = r_create.json()
    raw_key = data["key"]
    key_id = data["id"]

    # Verify key can authenticate
    r_me = client.get("/ui/me", headers={"Authorization": f"Bearer {raw_key}"})
    assert r_me.status_code == 200
    assert r_me.json()["role"] == "uploader"

    # Verify DB kv does NOT contain the raw key
    stored_keys = list_api_keys(db)
    target = [k for k in stored_keys if k.get("id") == key_id][0]
    assert "key" not in target
    assert target.get("key_hash") == hash_key(raw_key)

    # Clean up
    client.delete(f"/api/v1/admin/api-keys/{key_id}", headers=ADMIN)


def test_sec_b6_ssrf_validation():
    """SEC-B6: Validate SSRF blocking on private/loopback/metadata targets."""
    # Loopback
    with pytest.raises(ValueError, match="prohibited"):
        validate_url_target("http://127.0.0.1/admin")
    with pytest.raises(ValueError, match="prohibited"):
        validate_url_target("http://localhost:8000/info")

    # Cloud metadata
    with pytest.raises(ValueError, match="prohibited"):
        validate_url_target("http://169.254.169.254/latest/meta-data")

    # Private RFC 1918
    with pytest.raises(ValueError, match="prohibited"):
        validate_url_target("http://10.0.0.1/intranet")
    with pytest.raises(ValueError, match="prohibited"):
        validate_url_target("http://192.168.1.1/router")
    with pytest.raises(ValueError, match="prohibited"):
        validate_url_target("http://172.16.0.1/")

    # Non-http schemes
    with pytest.raises(ValueError, match="http"):
        validate_url_target("file:///etc/passwd")


def test_sec_b7_s3_put_overwrite_cleans_old_blobs(client: TestClient):
    """SEC-B7: S3 PUT overwrite must delete old object metadata & chunks without leak."""
    db = client.app.state.db
    # First upload
    client.put("/s3/mybucket/file.txt", headers=ADMIN, content=b"version 1")
    old_obj_id = db.kv_get("s3:mybucket:file.txt")
    assert old_obj_id is not None
    assert db.get_object(old_obj_id) is not None

    # Overwrite upload
    client.put("/s3/mybucket/file.txt", headers=ADMIN, content=b"version 2")
    new_obj_id = db.kv_get("s3:mybucket:file.txt")
    assert new_obj_id is not None
    assert new_obj_id != old_obj_id

    # Old object row must be deleted
    assert db.get_object(old_obj_id) is None


def test_rel_c1_jobqueue_uses_database_lock(client):
    """REL-C1: durable job rows synchronize through the shared Database lock."""
    jq = client.app.state.job_queue
    assert jq.store.db is client.app.state.db
    assert jq.store._conn is client.app.state.db.connection()


def test_sec_b8_security_headers_present(client: TestClient):
    """SEC-B8: HTML responses contain CSP, frame, referrer and MIME headers."""
    # HTML endpoint
    r_html = client.get("/")
    assert r_html.status_code == 200
    assert "Content-Security-Policy" in r_html.headers
    assert r_html.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert r_html.headers.get("X-Content-Type-Options") == "nosniff"
    assert "strict-origin" in r_html.headers.get("Referrer-Policy", "")


def test_sec_b9_album_subtitle_label_escaped(client: TestClient):
    """SEC-B9: Subtitle track labels in album gallery must be properly escaped."""
    # Upload a file
    r = client.post(
        "/api/v1/upload",
        files={"file": ("video.mp4", b"fake video data", "video/mp4")},
        headers=ADMIN,
    )
    assert r.status_code == 200
    obj_id = r.json()["id"]

    # Add subtitle track with malicious label
    xss_label = '"><script>alert("xss")</script>'
    r_sub = client.post(
        f"/api/v1/admin/objects/{obj_id}/subs",
        files={
            "file": (
                f"{xss_label}.vtt",
                b"WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\nHi",
                "text/vtt",
            )
        },
        data={"lang": "en", "label": xss_label},
        headers=ADMIN,
    )
    assert r_sub.status_code == 200, (r_sub.status_code, r_sub.text)

    # Create album
    r_alb = client.post("/f/album", json={"ids": [obj_id], "title": "Test Album"}, headers=ADMIN)
    assert r_alb.status_code == 200
    token = r_alb.json()["token"]

    # Fetch album page
    r_page = client.get(f"/f/a/{token}")
    assert r_page.status_code == 200
    # Must not contain unescaped script tag in body
    assert '<script>alert("xss")</script>' not in r_page.text
    assert "<script>alert" not in r_page.text
    assert "script&gt;" in r_page.text


def test_rel_c1_database_thread_lock(tmp_path):
    """REL-C1: Database exposes lock and synchronizes concurrent queries."""
    db = Database(tmp_path / "test.db")
    assert hasattr(db, "lock")

    async def worker(idx: int):
        for i in range(20):
            db.kv_set(f"key_{idx}_{i}", f"val_{i}")
            val = db.kv_get(f"key_{idx}_{i}")
            assert val == f"val_{i}"

    async def run_all():
        await asyncio.gather(*(worker(i) for i in range(5)))

    asyncio.run(run_all())
    assert db.kv_get("key_0_0") == "val_0"
    db.close()


def test_rel_c2_background_task_retention():
    """REL-C2: spawn_background_task retains reference in set until done."""

    async def sample_coro():
        await asyncio.sleep(0.05)
        return 42

    async def main():
        task = spawn_background_task(sample_coro(), name="sample-task")
        assert task in _BACKGROUND_TASKS
        await asyncio.sleep(0.1)
        assert task not in _BACKGROUND_TASKS

    asyncio.run(main())


def test_rel_c3_and_c4_accurate_counts_and_no_n_plus_one(client: TestClient):
    """REL-C3 and REL-C4: count_objects and get_system_stats accurate; sha256 in list_objects."""
    db = client.app.state.db
    # Verify count_objects
    cnt = db.count_objects()
    assert isinstance(cnt, int)
    assert cnt >= 0

    # Verify get_system_stats
    stats = db.get_system_stats()
    assert "total_objects" in stats
    assert "total_bytes" in stats
    assert "total_downloads" in stats
    assert "breakdown" in stats
    assert stats["total_objects"] == cnt

    # Verify admin system-stats returns accurate total_objects
    r = client.get("/api/v1/admin/system-stats", headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert body["total_objects"] == cnt

    # Verify REL-C4: list_objects provides sha256 directly
    objs = db.list_objects(limit=10)
    for obj in objs:
        assert "sha256" in obj
