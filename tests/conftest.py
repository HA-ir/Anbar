"""Shared test fixtures: app wired with FakeBackend, isolated env + temp DB."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from anbar.main import create_app
from anbar.storage import FakeBackend


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    """Tests must not see the developer's .env or ambient ANBAR_* variables.

    pydantic-settings reads `.env` from the CWD even when the variable is
    absent from the environment, so the CWD itself must leave the repo root.
    """
    monkeypatch.chdir(tmp_path)
    for var in (
        "ANBAR_BACKEND", "ANBAR_DB_PATH", "ANBAR_DATA_DIR", "ANBAR_BASE_URL",
        "ANBAR_AUTH_ENABLED", "ANBAR_BOT_TOKEN", "ANBAR_CHANNEL_ID",
        "ANBAR_ADMIN_KEY", "ANBAR_API_KEY", "ANBAR_HMAC_SECRET",
        "ANBAR_CACHE_ENABLED", "ANBAR_CACHE_DIR", "ANBAR_CACHE_MAX_MB",
        "ANBAR_MAX_UPLOAD_MB", "ANBAR_CHUNKING", "ANBAR_CHUNK_SIZE_MB",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANBAR_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("ANBAR_DATA_DIR", str(tmp_path))
    # auth is ON by design — give tests stable, known keys
    monkeypatch.setenv("ANBAR_API_KEY", "test-key")
    monkeypatch.setenv("ANBAR_ADMIN_KEY", "test-admin-key")
    monkeypatch.setenv("ANBAR_HMAC_SECRET", "test-hmac-secret")
    monkeypatch.setenv("ANBAR_BASE_URL", "http://testserver")
    from anbar.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture()
def client(backend):
    app = create_app(backend=backend)
    with TestClient(app) as c:
        yield c