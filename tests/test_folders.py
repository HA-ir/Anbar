"""
Integration test suite for Virtual Folders & Hierarchy in Anbar (v0.12.0).
Covers:
1. Creating virtual folder marker via /admin/folders/create.
2. S3 virtual hierarchy and prefix queries.
3. Rename/Move folder prefix via /admin/folders/rename.
4. Copy folder prefix via /admin/folders/copy.
5. Soft-delete folder prefix via /admin/folders/delete.
"""

from __future__ import annotations

import io


def test_folders_lifecycle_and_hierarchy(client):
    ADMIN = {"Authorization": "Bearer test-admin-key"}

    # 1. Create a folder
    r_create = client.post(
        "/api/v1/admin/folders/create", json={"path": "documents/reports"}, headers=ADMIN
    )
    assert r_create.status_code == 200
    data_create = r_create.json()
    assert data_create["status"] == "created"
    assert data_create["folder"] == "documents/reports/"

    # 2. Upload files inside that folder
    f1 = ("documents/reports/q1.pdf", b"%PDF-1.4 sample quarterly report", "application/pdf")
    f2 = ("documents/reports/summary.txt", b"Summary report text", "text/plain")

    r1 = client.post(
        "/api/v1/upload",
        files={"file": (f1[0], io.BytesIO(f1[1]), f1[2])},
        headers=ADMIN,
    )
    assert r1.status_code == 200

    r2 = client.post(
        "/api/v1/upload",
        files={"file": (f2[0], io.BytesIO(f2[1]), f2[2])},
        headers=ADMIN,
    )
    assert r2.status_code == 200

    # 3. Copy folder documents/reports -> backup/2026
    r_copy = client.post(
        "/api/v1/admin/folders/copy",
        json={"src_path": "documents/reports", "dst_path": "backup/2026"},
        headers=ADMIN,
    )
    assert r_copy.status_code == 200
    assert r_copy.json()["status"] == "copied"
    assert r_copy.json()["copied_count"] >= 2

    # Verify backup folder exists and can be retrieved via S3
    r_s3_ls = client.get("/s3/backup", headers=ADMIN)
    assert r_s3_ls.status_code == 200
    assert "2026/q1.pdf" in r_s3_ls.text
    assert "2026/summary.txt" in r_s3_ls.text

    # 4. Rename/Move folder backup/2026 -> archive/reports
    r_rename = client.post(
        "/api/v1/admin/folders/rename",
        json={"old_path": "backup/2026", "new_path": "archive/reports"},
        headers=ADMIN,
    )
    assert r_rename.status_code == 200
    assert r_rename.json()["status"] == "renamed"

    r_s3_arch = client.get("/s3/archive", headers=ADMIN)
    assert "reports/q1.pdf" in r_s3_arch.text

    # 5. Soft-delete folder archive/reports
    r_del = client.post(
        "/api/v1/admin/folders/delete",
        json={"path": "archive/reports"},
        headers=ADMIN,
    )
    assert r_del.status_code == 200
    assert r_del.json()["status"] == "deleted"
    assert r_del.json()["deleted_count"] >= 2
