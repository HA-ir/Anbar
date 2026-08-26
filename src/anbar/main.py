"""anbar: Telegram-backed object storage (zero local file retention)."""
from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import __version__
from .config import get_settings
from .db import Database
from .storage import StorageBackend


def _configure_logging(level_name: str) -> None:
    """Basic stderr logging for anbar loggers.

    Without this the `anbar.*` loggers fall back to the root logger's
    last-resort WARNING handler and every INFO line (flood waits, chunk
    sends, rollback notices) is silently dropped — which made the 500 MB
    hang undiagnosable in production (v0.8.4).
    """
    import logging

    logging.basicConfig(
        level=getattr(logging, level_name.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def create_app(backend: StorageBackend | None = None) -> FastAPI:
    """App factory. `backend` injectable for tests (FakeBackend)."""
    settings = get_settings()
    _configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(settings.db_path)
        app.state.db = db
        injected = backend is not None
        app.state.backend = backend or _default_backend(settings)
        app.state.settings = settings
        if hasattr(app.state.backend, "connect"):
            await app.state.backend.connect()
        app.state.cache = _build_cache(settings, db)

        # Hybrid support: initialize bot_client and harvester if bot credentials exist
        app.state.bot_client = None
        app.state.harvester = None
        if settings.bot_token and settings.channel_id:
            from .storage.bot_backend import BotBackend
            from .storage.bot_harvester import BotHarvester
            bot_tok = settings.bot_token.get_secret_value()
            if isinstance(app.state.backend, BotBackend):
                app.state.bot_client = app.state.backend
            else:
                app.state.bot_client = BotBackend(
                    bot_tok,
                    settings.channel_id,
                    send_gap_s=settings.flood_send_gap_s,
                    flood_budget_s=settings.flood_budget_s,
                    send_timeout_s=settings.send_timeout_s,
                )
            app.state.harvester = BotHarvester(bot_tok, settings.channel_id, db=db)
            await app.state.harvester.start()

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
        if app.state.harvester is not None:
            await app.state.harvester.stop()
        if app.state.bot_client is not None and app.state.bot_client is not app.state.backend:
            await app.state.bot_client.close()
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
    from .api import ingest  # local import: optional URL-ingest feature
    app.include_router(ingest.router, prefix="/api/v1", tags=["ingest"])
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

        return BotBackend(
            settings.bot_token.get_secret_value(),
            settings.channel_id,
            send_gap_s=settings.flood_send_gap_s,
            flood_budget_s=settings.flood_budget_s,
            send_timeout_s=settings.send_timeout_s,
        )
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
            peer=settings.mtproto_peer,
            export_conns=getattr(settings, "mtproto_export_conns", 0),
        )
    raise RuntimeError(f"unknown backend {settings.backend!r}")


def _build_cache(settings, db=None):
    """LRU object cache if enabled (F6); None otherwise (zero overhead).

    Honours the persisted ``cache_mb`` runtime override when ``db`` is
    given, but never the master switch: with ``ANBAR_CACHE_ENABLED=false``
    the cache stays off no matter what.
    """
    if not settings.cache_enabled:
        return None
    budget_mb = settings.cache_max_mb
    if db is not None:
        from . import runtime
        budget_mb = runtime.get_int(db, "cache_mb", settings.cache_max_mb)
    if budget_mb <= 0:
        return None
    from .cache import DiskLRU

    return DiskLRU(settings.cache_dir, budget_mb * 1024 * 1024)