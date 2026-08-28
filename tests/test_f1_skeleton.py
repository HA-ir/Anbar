"""F1: app boots, healthz, config validation."""

from __future__ import annotations

import pytest


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "anbar"


def test_admin_status(client):
    r = client.get("/api/v1/admin/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["backend"] == "fake"
    assert isinstance(body["objects"], int)


def test_upload_roundtrip_fake(backend, client):
    import hashlib

    payload = b"x" * (20 * 1024 * 1024 + 123)  # splits into 16MB + 4MB+123
    r = client.post(
        "/api/v1/upload",
        files={"file": ("big.bin", payload, "application/octet-stream")},
        headers={"Authorization": "Bearer test-key"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["size"] == len(payload)
    assert body["sha256"] == hashlib.sha256(payload).hexdigest()
    assert body["chunks"] == 2
    assert body["url"].endswith(f"/f/{body['id']}")

    from anbar.objects import Manifest
    from anbar.storage import ObjectRef

    row = client.app.state.db.get_object(body["id"])
    assert row["size"] == len(payload)
    assert row["sha256"] == hashlib.sha256(payload).hexdigest()
    m = Manifest.from_json(row["manifest"])
    assert m.total_size == len(payload)
    assert len(m.chunks) == 2
    assert m.chunks[0].size == 16 * 1024 * 1024
    assert m.chunks[1].size == 4 * 1024 * 1024 + 123
    # each stored chunk is retrievable from the backend
    import asyncio

    for c in m.chunks:
        data = asyncio.run(backend.open(ObjectRef(file_id=c.file_id, backend="fake")))
        assert len(data) == c.size


def test_download_unknown_object(client):
    r = client.get("/f/nonexistent123")
    assert r.status_code == 404


class TestConfig:
    def test_defaults(self):
        from anbar.config import get_settings

        get_settings.cache_clear()
        s = get_settings()
        assert s.auth_enabled is True
        assert s.backend.value == "bot"
        assert s.chunking.value == "auto"
        assert s.max_upload_bytes() == 10240 * 1024 * 1024

    def test_port_bounds(self):
        from pydantic import ValidationError

        from anbar.config import Settings, get_settings

        with pytest.raises(ValidationError):
            Settings(port=70000)
        get_settings.cache_clear()
