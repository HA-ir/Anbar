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


def _upload(client, filename, data=b"hello", ct="text/plain", headers=None):
    return client.post(
        "/api/v1/upload",
        files={"file": (filename, io.BytesIO(data), ct)},
        headers=headers or {},
    ).json()


def test_move_objects(client):
    ADMIN = {"Authorization": "Bearer test-admin-key"}
    a = _upload(client, "report.pdf", b"%PDF-1.4 A", headers=ADMIN)
    b = _upload(client, "notes/report.pdf", b"%PDF-1.4 B", headers=ADMIN)
    c = _upload(client, "notes/draft.txt", b"draft text", headers=ADMIN)

    # Move two objects into a new folder "archive"
    r = client.post(
        "/api/v1/admin/objects/move",
        json={"ids": [a["id"], c["id"]], "dest": "archive"},
        headers=ADMIN,
    )
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "moved"
    assert j["moved"] == 2
    assert j["skipped"] == []
    assert j["dest"] == "archive/"

    names = client.get("/api/v1/admin/objects", headers=ADMIN).json()
    fns = sorted(o["filename"] for o in names["objects"])
    assert "archive/report.pdf" in fns
    assert "archive/draft.txt" in fns
    # the untouched file stays where it was
    assert "notes/report.pdf" in fns

    # Trailing slash + dot-path are normalized the same way
    r = client.post(
        "/api/v1/admin/objects/move",
        json={"ids": [b["id"]], "dest": "archive/deep/"},
        headers=ADMIN,
    )
    assert r.json()["moved"] == 1
    objs = client.get("/api/v1/admin/objects", headers=ADMIN).json()["objects"]
    fns = sorted(o["filename"] for o in objs)
    assert "archive/deep/report.pdf" in fns

    # Basename preserved on re-move: archive/deep/report.pdf -> root
    r = client.post(
        "/api/v1/admin/objects/move",
        json={"ids": [b["id"]], "dest": ""},
        headers=ADMIN,
    )
    assert r.json()["moved"] == 1
    objs = client.get("/api/v1/admin/objects", headers=ADMIN).json()["objects"]
    fns = sorted(o["filename"] for o in objs)
    assert "report.pdf" in fns
    assert "archive/deep/report.pdf" not in fns


def test_move_objects_collision_skipped(client):
    ADMIN = {"Authorization": "Bearer test-admin-key"}
    x = _upload(client, "file.txt", b"one", headers=ADMIN)
    y = _upload(client, "other/file.txt", b"two", headers=ADMIN)

    r = client.post(
        "/api/v1/admin/objects/move",
        json={"ids": [x["id"], y["id"]], "dest": ""},
        headers=ADMIN,
    )
    assert r.status_code == 200
    j = r.json()
    # x is already at root (no-op, counted), y collides with x
    assert j["moved"] == 1
    assert len(j["skipped"]) == 1
    assert j["skipped"][0]["id"] == y["id"]
    assert j["skipped"][0]["reason"] == "exists"
    # nothing was overwritten
    objs = client.get("/api/v1/admin/objects", headers=ADMIN).json()["objects"]
    fns = sorted(o["filename"] for o in objs)
    assert fns.count("file.txt") == 1


def test_move_objects_validation(client):
    ADMIN = {"Authorization": "Bearer test-admin-key"}
    a = _upload(client, "a.txt", b"aaa", headers=ADMIN)

    # empty ids
    r = client.post("/api/v1/admin/objects/move", json={"ids": [], "dest": "x"}, headers=ADMIN)
    assert r.status_code == 400

    # missing dest field → moves to root (valid)
    r = client.post("/api/v1/admin/objects/move", json={"ids": [a["id"]]}, headers=ADMIN)
    assert r.status_code == 200

    # invalid single-segment dest
    r = client.post(
        "/api/v1/admin/objects/move", json={"ids": [a["id"]], "dest": "bad?name"}, headers=ADMIN
    )
    assert r.status_code == 400

    # unknown ids → moved 0, skipped 0 (not an error)
    r = client.post(
        "/api/v1/admin/objects/move", json={"ids": ["doesnotexist"], "dest": "x"}, headers=ADMIN
    )
    assert r.status_code == 200
    assert r.json()["moved"] == 0

    # non-admin cannot move
    r = client.post(
        "/api/v1/admin/objects/move", json={"ids": [a["id"]], "dest": "x"}
    )
    assert r.status_code == 401


def test_folder_rename_into_itself_rejected(client):
    ADMIN = {"Authorization": "Bearer test-admin-key"}
    r = client.post(
        "/api/v1/admin/folders/create", json={"path": "docs/reports"}, headers=ADMIN
    )
    assert r.status_code == 200

    # moving into itself
    r = client.post(
        "/api/v1/admin/folders/rename",
        json={"old_path": "docs/reports", "new_path": "docs/reports"},
        headers=ADMIN,
    )
    assert r.status_code == 400

    # moving into one of its own subfolders
    r = client.post(
        "/api/v1/admin/folders/rename",
        json={"old_path": "docs/reports", "new_path": "docs/reports/old"},
        headers=ADMIN,
    )
    assert r.status_code == 400

    # legitimate move still works
    r = client.post(
        "/api/v1/admin/folders/rename",
        json={"old_path": "docs/reports", "new_path": "archive/reports"},
        headers=ADMIN,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "renamed"
