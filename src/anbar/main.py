"""anbar: Telegram-backed object storage (zero local file retention)."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from .db import Database
from .storage import StorageBackend


def create_app(backend: StorageBackend | None = None) -> FastAPI:
    """App factory. `backend` injectable for tests (FakeBackend)."""
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(settings.db_path)
        app.state.db = db
        app.state.backend = backend or _default_backend(settings)
        app.state.settings = settings
        yield
        db.close()

    app = FastAPI(title="anbar", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"status": "ok", "service": "anbar", "version": "0.1.0"}

    from .api import admin, download, upload  # noqa: PLC0415

    app.include_router(upload.router, prefix="/api/v1", tags=["upload"])
    app.include_router(download.router, prefix="/f", tags=["download"])
    app.include_router(admin.router, prefix="/api/v1", tags=["admin"])
    return app


def _default_backend(settings) -> StorageBackend:
    """F1: FakeBackend for dev/CI. F2 wires BotBackend; F5 adds MTProto selection."""
    if settings.backend.value == "fake":
        from .storage import FakeBackend

        return FakeBackend()
    if settings.backend.value == "bot":
        raise RuntimeError(
            "BotBackend lands in F2. Until then, run tests (FakeBackend) or set "
            "ANBAR_BACKEND=fake."
        )
    raise RuntimeError(f"backend {settings.backend.value} not available yet")


app = None  # created on demand: uvicorn anbar.main:create_app --factory