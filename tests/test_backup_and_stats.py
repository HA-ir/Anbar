from __future__ import annotations

import io

from starlette.testclient import TestClient

ADMIN = {"Authorization": "Bearer test-admin-key"}


def test_backup_and_system_stats(client: TestClient):
    # 1. Login
    client.post("/ui/login", json={"key": "test-admin-key"})

    # 2. Upload a sample file
    r_up = client.post(
        "/api/v1/upload",
        files={"file": ("test_doc.txt", io.BytesIO(b"Hello world"), "text/plain")},
        headers=ADMIN,
    )
    assert r_up.status_code == 200

    # 3. Test backup download
    r_bk = client.get("/api/v1/admin/backup", headers=ADMIN)
    assert r_bk.status_code == 200
    assert len(r_bk.content) > 0
    assert "attachment; filename=\"anbar_backup_" in r_bk.headers.get("content-disposition", "")

    # 4. Test backup push to telegram (ARCH-02: queued via the job queue)
    r_tg = client.post("/api/v1/admin/backup/telegram", headers=ADMIN)
    assert r_tg.status_code == 200
    tg_body = r_tg.json()
    assert tg_body["status"] in ("ok", "queued")
    job_id = tg_body.get("job_id")
    if tg_body["status"] == "queued":
        # poll the job until done (FakeBackend store is instant; bounded loop)
        import time as _time

        deadline = _time.time() + 10
        job_row = None
        while _time.time() < deadline:
            r_job = client.get(f"/api/v1/admin/jobs/{job_id}", headers=ADMIN)
            assert r_job.status_code == 200
            job_row = r_job.json()
            if job_row["state"] in ("done", "error"):
                break
            _time.sleep(0.05)
        assert job_row is not None and job_row["state"] == "done", job_row
        assert "file_id" in job_row["result"]
    else:
        assert "file_id" in tg_body
    # last_backup_time is set by the job handler (or inline fallback)
    r_st_probe = client.get("/api/v1/admin/system-stats", headers=ADMIN)
    assert r_st_probe.status_code == 200

    # 5. Test system stats
    r_st = client.get("/api/v1/admin/system-stats", headers=ADMIN)
    assert r_st.status_code == 200
    data = r_st.json()
    assert data["status"] == "healthy"
    assert data["total_objects"] >= 1
    assert data["last_backup_time"] is not None

    # 6. Test backup import / restore
    backup_data = r_bk.content
    r_imp = client.post(
        "/api/v1/admin/backup/import",
        files={"file": ("restore_test.db", io.BytesIO(backup_data), "application/vnd.sqlite3")},
        headers=ADMIN,
    )
    assert r_imp.status_code == 200
    imp_json = r_imp.json()
    assert imp_json["status"] == "ok"
    assert imp_json["restored"] is True
    assert imp_json["objects_count"] >= 1

    # 7. Test invalid backup import error handling
    r_bad = client.post(
        "/api/v1/admin/backup/import",
        files={"file": ("corrupt.db", io.BytesIO(b"Not an sqlite db"), "application/octet-stream")},
        headers=ADMIN,
    )
    assert r_bad.status_code == 400

    # 8. Test breakdown and audit logs
    assert "breakdown" in data
    assert "image" in data["breakdown"]
    assert "text" in data["breakdown"]

    r_audit = client.get("/api/v1/admin/audit-logs", headers=ADMIN)
    assert r_audit.status_code == 200
    assert "logs" in r_audit.json()

