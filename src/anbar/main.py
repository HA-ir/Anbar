"""anbar: Telegram-backed object storage (zero local file retention)."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import __version__
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
        injected = backend is not None
        app.state.backend = backend or _default_backend(settings)
        app.state.settings = settings
        if hasattr(app.state.backend, "connect"):
            await app.state.backend.connect()
        app.state.cache = _build_cache(settings)

        async def _prune_rate_loop() -> None:
            """Drop finished rate windows so the table doesn't grow forever."""
            while True:
                await asyncio.sleep(600)
                try:
                    db.rate_prune()
                except Exception:  # pragma: no cover - db already closed
                    return

        prune_task = asyncio.create_task(_prune_rate_loop())
        yield
        prune_task.cancel()
        if app.state.cache is not None:
            app.state.cache.close()
        db.close()
        if not injected:
            await app.state.backend.close()

    app = FastAPI(title="anbar", version=__version__, lifespan=lifespan)
    app.state.settings = settings

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"status": "ok", "service": "anbar", "version": __version__}

    from .api import admin, download, upload, web  # noqa: PLC0415

    app.include_router(upload.router, prefix="/api/v1", tags=["upload"])
    app.include_router(download.router, prefix="/f", tags=["download"])
    app.include_router(admin.router, prefix="/api/v1", tags=["admin"])
    app.include_router(web.router, tags=["web ui"])
    return app


def _default_backend(settings) -> StorageBackend:
    """Wire the configured backend. F2: bot; F5: mtproto selection."""
    if settings.backend.value == "fake":
        from .storage import FakeBackend

        return FakeBackend()
    if settings.backend.value == "bot":
        if not settings.bot_token or not settings.channel_id:
            raise RuntimeError(
                "backend=bot requires ANBAR_BOT_TOKEN and ANBAR_CHANNEL_ID "
                "(see docs/DEPLOY.md 'Creating the channel')."
            )
        from .storage import BotBackend

        return BotBackend(settings.bot_token.get_secret_value(), settings.channel_id)
    if settings.backend.value == "mtproto":
        if not settings.api_id or not settings.api_hash:
            raise RuntimeError(
                "backend=mtproto requires ANBAR_API_ID and ANBAR_API_HASH from "
                "my.telegram.org (see docs/DEPLOY.md 'MTProto backend')."
            )
        from .storage import MTProtoBackend

        return MTProtoBackend(
            api_id=settings.api_id,
            api_hash=settings.api_hash,
            session_file=str(settings.session_file),
        )
    raise RuntimeError(f"unknown backend {settings.backend!r}")


def _build_cache(settings):
    """LRU object cache if enabled (F6); None otherwise (zero overhead)."""
    if not settings.cache_enabled:
        return None
    from .cache import DiskLRU

    return DiskLRU(settings.cache_dir, settings.cache_max_mb * 1024 * 1024)