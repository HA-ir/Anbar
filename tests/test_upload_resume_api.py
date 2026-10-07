"""Unit and integration tests for upload resume discovery endpoint."""

from __future__ import annotations

import json

from starlette.testclient import TestClient

ADMIN = {"Authorization": "Bearer test-admin-key"}


def test_upload_resume_requires_uploader(client: TestClient):
    res = client.get("/api/v1/upload/resume/q12345")
    assert res.status_code == 401


def test_upload_resume_not_found(client: TestClient):
    client.post("/ui/login", json={"key": "test-admin-key"})
    res = client.get("/api/v1/upload/resume/non_existent_id", headers=ADMIN)
    assert res.status_code == 200
    data = res.json()
    assert data["upload_id"] == "non_existent_id"
    assert data["exists"] is False
    assert data["chunks_done"] == 0
    assert data["bytes_done"] == 0


def test_upload_resume_with_checkpoint(client: TestClient):
    client.post("/ui/login", json={"key": "test-admin-key"})
    app_state = client.app.state  # type: ignore[attr-defined]
    db = app_state.db
    upload_id = "test_resume_q99"
    checkpoint = {
        "_ts": 1720000000,
        "chunks": [
            {"s": 16 * 1024 * 1024, "f": "f1", "m": 1},
            {"s": 16 * 1024 * 1024, "f": "f2", "m": 2},
        ],
    }
    db.kv_set(f"upres:{upload_id}", json.dumps(checkpoint))

    res = client.get(f"/api/v1/upload/resume/{upload_id}", headers=ADMIN)
    assert res.status_code == 200
    data = res.json()
    assert data["upload_id"] == upload_id
    assert data["exists"] is True
    assert data["chunks_done"] == 2
    assert data["bytes_done"] == 32 * 1024 * 1024
    assert data["timestamp"] == 1720000000
