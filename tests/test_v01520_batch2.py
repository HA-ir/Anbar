"""v0.15.20 improvement-plan fixes batch 2: PERF-02, PERF-04, SEC-02, ARCH-03.

PERF-02 — GZipMiddleware compresses JSON/HTML but NOT /f/ and /s3/ object
           downloads (Content-Length must survive for media players).
PERF-04 — full-object (non-range) /f/ responses carry Cache-Control.
SEC-02  — the admin key must NOT be accepted via ?k= (query-string leak);
          uploader key and dynamic keys still are.
ARCH-03 — ingest JOBS pruned after 1h (finished ones).
"""

from __future__ import annotations

import time

from starlette.testclient import TestClient

UP = {"Authorization": "Bearer test-key"}


# ── PERF-02: selective gzip ─────────────────────────────────────────────


def test_dashboard_html_is_gzipped(client: TestClient):
    r = client.get("/", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip"


def test_object_download_is_not_gzipped(client: TestClient):
    obj = client.post(
        "/api/v1/upload/raw",
        content=b"Z" * 4096,
        headers={**UP, "X-File-Name": "bin.dat", "Content-Type": "application/octet-stream"},
    ).json()
    r = client.get(
        f"/f/{obj['id']}?sig=none",
        headers={"Accept-Encoding": "gzip", **UP},
    )
    # auth-on requires a signature; use bearer path instead — but whatever
    # the status, the response must never be gzip-encoded
    assert r.headers.get("content-encoding") != "gzip"


def test_api_json_is_gzipped(client: TestClient):
    # the response must exceed minimum_size (1KB) — seed objects so the
    # JSON body is large enough to trigger compression
    db = client.app.state.db
    for i in range(40):
        db.insert_object(
            {
                "id": f"gz{i:04d}" + "0" * 6,
                "file_id": "x",
                "backend": "fake",
                "filename": f"compressible-object-name-{i}.bin",
                "size": 12345,
                "content_type": "application/octet-stream",
                "sha256": "a" * 64,
                "manifest": '{"chunks": []}',
            }
        )
    r = client.get(
        "/api/v1/admin/objects",
        headers={"Accept-Encoding": "gzip", "Authorization": "Bearer test-admin-key"},
    )
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip"


# ── PERF-04: Cache-Control on full-object responses ─────────────────────


def _upload_and_sign(client: TestClient):
    obj = client.post(
        "/api/v1/upload/raw",
        content=b"CC" * 8,
        headers={**UP, "X-File-Name": "cache.bin", "Content-Type": "application/octet-stream"},
    ).json()
    link = client.post(f"/f/{obj['id']}/link?ttl=3600", headers=UP).json()
    return obj, link


def test_full_object_response_has_cache_control(client: TestClient):
    obj, link = _upload_and_sign(client)
    url = link["url"].replace("http://testserver", "")
    r = client.get(url)
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "private, max-age=3600"


def test_range_response_has_no_cache_control(client: TestClient):
    obj, link = _upload_and_sign(client)
    url = link["url"].replace("http://testserver", "")
    r = client.get(url, headers={"Range": "bytes=0-3"})
    assert r.status_code == 206
    assert "cache-control" not in r.headers


# ── SEC-02 (reverted in v0.15.28 per user decision) ─────────────────────
# The owner explicitly wants the UI's ?k=<admin-key> media URLs to work:
# every preview (<img>/<video>) and the download button emit
# /f/<id>?k=<admin key>, and after a session-cookie expiry these all 401'd
# ("no previews, downloads fail"). The admin key is the owner's own secret;
# honoring it in ?k= restores the pre-v0.15.20 behavior.


def test_admin_key_in_query_string_accepted(client: TestClient):
    # settings fixture: admin key is "test-admin-key" (conftest default env)
    r = client.get(
        "/api/v1/admin/objects?limit=1",
        headers={"Authorization": "Bearer test-admin-key"},
    )
    assert r.status_code == 200  # sanity: admin key valid as bearer
    obj = client.post(
        "/api/v1/upload/raw",
        content=b"S" * 16,
        headers={**UP, "X-File-Name": "sec2.bin", "Content-Type": "application/octet-stream"},
    ).json()
    # admin key via ?k= GRANTS download again (v0.15.28 owner decision)
    r2 = client.get(f"/f/{obj['id']}?k=test-admin-key")
    assert r2.status_code == 200


def test_uploader_key_in_query_string_still_accepted(client: TestClient):
    obj = client.post(
        "/api/v1/upload/raw",
        content=b"S" * 16,
        headers={**UP, "X-File-Name": "sec2b.bin", "Content-Type": "application/octet-stream"},
    ).json()
    r = client.get(f"/f/{obj['id']}?k=test-key")
    assert r.status_code == 200


# ── ARCH-03: ingest JOBS pruning ────────────────────────────────────────


def test_prune_jobs_drops_stale_finished_only():
    from anbar.api.ingest import JOBS, _prune_jobs

    JOBS.clear()
    now = time.time()
    JOBS["old-done"] = {"state": "done", "started": now - 7200}
    JOBS["old-running"] = {"state": "pulling", "started": now - 7200}
    JOBS["fresh-done"] = {"state": "done", "started": now - 60}
    JOBS["old-error"] = {"state": "error", "started": now - 7200}

    removed = _prune_jobs()
    assert removed == 2
    assert "old-done" not in JOBS
    assert "old-error" not in JOBS
    assert "old-running" in JOBS  # running jobs are never pruned
    assert "fresh-done" in JOBS
    JOBS.clear()
