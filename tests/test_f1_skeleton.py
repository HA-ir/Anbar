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


def test_upload_not_implemented_yet(client):
    r = client.post("/api/v1/upload")
    assert r.status_code == 501


def test_download_not_implemented_yet(client):
    r = client.get("/f/abc123")
    assert r.status_code == 501


class TestConfig:
    def test_defaults(self):
        from anbar.config import get_settings

        get_settings.cache_clear()
        s = get_settings()
        assert s.auth_enabled is True
        assert s.backend.value == "bot"
        assert s.chunking.value == "auto"
        assert s.max_upload_bytes() == 2000 * 1024 * 1024

    def test_port_bounds(self):
        from pydantic import ValidationError

        from anbar.config import Settings, get_settings

        with pytest.raises(ValidationError):
            Settings(port=70000)
        get_settings.cache_clear()