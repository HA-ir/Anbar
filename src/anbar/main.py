"""anbar: Telegram-backed object storage (zero local file retention)."""

from __future__ import annotations

import asyncio
import sys
import time
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

        # PERF-01: RAM-only micro cache for chunk re-fetches during seeking
        from . import runtime
        from .cache import ChunkMicroCache

        seek_mb = runtime.get_int(db, "seek_cache_mb", settings.seek_cache_mb)
        app.state.chunk_cache = (
            ChunkMicroCache(seek_mb * 1024 * 1024) if seek_mb > 0 else None
        )

        # ARCH-02: durable job queue (jobs table in the same SQLite DB)
        from .jobqueue import JobQueue

        JobQueue._ensure_table(db)
        jq = JobQueue(db)
        jq.mark_interrupted_on_boot()  # in-flight rows died with the old process
        app.state.job_queue = jq

        # Hybrid support: initialize bot_pool and harvester if bot credentials exist
        app.state.bot_client = None
        app.state.bot_pool = None
        app.state.harvester = None
        tokens = settings.bot_tokens
        if tokens and settings.channel_id:
            from .storage.bot_harvester import BotHarvester
            from .storage.bot_pool import BotPool

            app.state.bot_pool = BotPool(
                tokens,
                settings.channel_id,
                send_gap_s=settings.flood_send_gap_s,
                flood_budget_s=settings.flood_budget_s,
                send_timeout_s=settings.send_timeout_s,
            )
            # ARCH-01: when the bot pool IS the storage backend (backend=bot),
            # meta/event traffic rides the primary member — matching chunk #0's
            # holder, which keeps legacy file_id refs (row["file_id"]) valid.
            app.state.bot_client = app.state.bot_pool.primary
            app.state.harvester = BotHarvester(tokens[0], settings.channel_id, db=db)
            await app.state.harvester.start()

        async def _prune_rate_loop() -> None:
            """Drop finished rate windows + stale resume checkpoints.

            - rate windows: table grows forever if this loop dies (v0.15.16)
            - upres:* resume checkpoints: cleaned on commit since v0.15.20,
              but uploads abandoned mid-flight leave orphans behind — drop
              any older than 24h (the documented checkpoint lifetime).
            """
            while True:
                await asyncio.sleep(600)
                try:
                    db.rate_prune()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # transient errors (e.g. db busy) must not kill the loop —
                    # a dead prune loop lets the rate_windows table grow forever
                    continue
                try:
                    db.kv_prune_prefix("upres:", max_age_s=86400)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    continue
                try:
                    # BUG-v0.15.26b: reap expired album tokens (they carry _ts)
                    db.kv_prune_prefix("album:", max_age_s=86400 * 31)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    continue
                try:
                    db.audit_prune()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    continue
                # ARCH-02: prune finished job rows after 1h (same TTL rule as
                # the old in-memory JOBS dict)
                try:
                    jq = getattr(app.state, "job_queue", None)
                    if jq is not None:
                        jq.prune()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    continue

        async def _auto_backup_loop() -> None:
            """Periodic database snapshot push to Telegram (every 24 hours)."""
            from . import runtime
            while True:
                await asyncio.sleep(86400)
                try:
                    is_enabled = bool(
                        runtime.get_int(
                            db,
                            "auto_backup_enabled",
                            1 if getattr(settings, "auto_backup_enabled", True) else 0,
                        )
                    )
                    if not is_enabled:
                        continue
                    last_bk = db.kv_get("last_backup_time")
                    now_ts = int(time.time())
                    if not last_bk or now_ts - int(last_bk) >= 86400:
                        data = db.backup_bytes()
                        ts_str = time.strftime("%Y%m%d_%H%M%S")
                        filename = f"anbar_autobackup_{ts_str}.db"
                        backend = app.state.backend
                        if backend and hasattr(backend, "store"):
                            await backend.store(
                                data, filename, content_type="application/x-sqlite3"
                            )
                            db.kv_set("last_backup_time", str(now_ts))
                            db.log_audit(
                                "backup.auto",
                                actor="system",
                                target=filename,
                                details={"size": len(data)},
                            )
                except Exception:  # pragma: no cover
                    pass

        prune_task = asyncio.create_task(_prune_rate_loop())
        backup_task = asyncio.create_task(_auto_backup_loop())
        yield
        jq = getattr(app.state, "job_queue", None)
        if jq is not None:
            await jq.stop()
        prune_task.cancel()
        backup_task.cancel()
        if app.state.harvester is not None:
            await app.state.harvester.stop()
        if app.state.bot_pool is not None:
            await app.state.bot_pool.close()
        if app.state.cache is not None:
            app.state.cache.close()
        cc = getattr(app.state, "chunk_cache", None)
        if cc is not None:
            cc.close()
        db.close()
        if not injected:
            await app.state.backend.close()

    app = FastAPI(title="anbar", version=__version__, lifespan=lifespan)
    app.state.settings = settings

    # PERF-02 (v0.15.20): compress text responses > 1KB (the 210KB dashboard
    # is ~52KB gzipped). Object downloads (/f/, /s3/) are excluded: they are
    # already-compressed binary media streamed with Content-Length, and
    # gzipping them strips the header the range/player logic relies on.
    from fastapi.middleware.gzip import GZipMiddleware

    class _SelectiveGZip(GZipMiddleware):
        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                path = scope.get("path", "")
                if path.startswith("/f/") or path.startswith("/s3/"):
                    await self.app(scope, receive, send)
                    return
            await super().__call__(scope, receive, send)

    app.add_middleware(_SelectiveGZip, minimum_size=1000)

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"status": "ok", "service": "anbar", "version": __version__}

    from .api import admin, download, s3, upload, web  # noqa: PLC0415

    app.include_router(upload.router, prefix="/api/v1", tags=["upload"])
    from .api import ingest  # local import: optional URL-ingest feature

    app.include_router(ingest.router, prefix="/api/v1", tags=["ingest"])
    app.include_router(download.router, prefix="/f", tags=["download"])
    app.include_router(s3.router, tags=["s3"])
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
            channel_thread_id=settings.channel_thread_id,
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
