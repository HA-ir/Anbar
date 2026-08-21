"""Shared test fixtures: app wired with FakeBackend, isolated temp DB."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tglink.main import create_app
from tglink.storage import FakeBackend


@pytest.fixture()
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture()
def client(backend, tmp_path, monkeypatch):
    monkeypatch.setenv("TGLINK_BACKEND", "fake")
    monkeypatch.setenv("TGLINK_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("TGLINK_DATA_DIR", str(tmp_path))
    # clear lru_cache so settings re-read env
    from tglink.config import get_settings

    get_settings.cache_clear()
    app = create_app(backend=backend)
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()