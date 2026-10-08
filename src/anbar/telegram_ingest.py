"""Streaming ingestion pipeline for Telegram Bot webhook updates.

Supports:
- Mode A: Direct forwarded / uploaded media (document, video, audio, photo)
  -> Small files (<= 20MB): Downloaded via Bot API getFile.
  -> Large files (> 20MB) or fallback: Downloaded via MTProto (Telethon).
  -> All Telegram downloads upload to Anbar via Bot Tokens (anti-ban routing).
- Mode B: Restricted / protected channel post links (t.me/c/... or t.me/...) via MTProto.
- Mode C: External Web URLs (http:// or https://) streamed via HTTP into configured backend.
- Real-time live status updates with speed, progress bar, and estimated time (ETA).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import httpx

from .api.ingest import _filename_from_url, _guess_content_type
from .ingest_manager import TASK_MANAGER
from .mtproto_provider import get_active_mtproto_client
from .object_service import ObjectService
from .tasks import spawn_background_task

if TYPE_CHECKING:
    from fastapi import FastAPI

log = logging.getLogger("anbar.tg_ingest")

RE_PRIVATE_POST = re.compile(r"t\.me/c/(\d+)/(\d+)")
RE_PUBLIC_POST = re.compile(r"t\.me/([a-zA-Z0-9_]{4,})/(\d+)")
RE_WEB_URL = re.compile(r"https?://[^\s]+", re.IGNORECASE)


def format_size(num_bytes: int | float | None) -> str:
    """Format byte count into human readable units."""
    if not num_bytes or num_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    b = float(num_bytes)
    idx = 0
    while b >= 1024.0 and idx < len(units) - 1:
        b /= 1024.0
        idx += 1
    return f"{b:.2f} {units[idx]}" if idx > 0 else f"{int(b)} B"


def format_eta(seconds: float | int | None) -> str:
    """Format seconds into human-readable ETA (e.g. '1m 24s', '45s')."""
    if seconds is None or seconds < 0:
        return "calculating..."
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m = s // 60
    rem_s = s % 60
    if m < 60:
        return f"{m}m {rem_s:02d}s"
    h = m // 60
    rem_m = m % 60
    return f"{h}h {rem_m:02d}m"


def render_progress_bar(pct: float, length: int = 10) -> str:
    """Render a text progress bar."""
    filled = max(0, min(length, int(round(length * pct / 100))))
    return "█" * filled + "░" * (length - filled)


def parse_telegram_post_link(text: str) -> tuple[int | str, int] | None:
    """Extract (entity, message_id) from a Telegram message link."""
    # 1. Private channel / supergroup: t.me/c/<channel_id>/<msg_id>
    m_priv = RE_PRIVATE_POST.search(text)
    if m_priv:
        raw_cid, mid = m_priv.groups()
        channel_id = int(f"-100{raw_cid}")
        return channel_id, int(mid)

    # 2. Public channel / group: t.me/<username>/<msg_id>
    m_pub = RE_PUBLIC_POST.search(text)
    if m_pub:
        username, mid = m_pub.groups()
        if username.lower() not in ("joinchat", "share", "addstickers", "invoice", "c"):
            return username, int(mid)

    return None


def parse_web_url(text: str) -> str | None:
    """Extract standard external web URL from text (ignoring t.me links)."""
    m = RE_WEB_URL.search(text)
    if m:
        url = m.group(0).strip(")>],.\"';")
        url_lower = url.lower()
        if "t.me/" not in url_lower and "telegram.me/" not in url_lower:
            return url
    return None


def get_bot_storage_backend(app: Any):
    """Retrieve BotBackend or BotPool to guarantee uploads go through Bot tokens."""
    settings = app.state.settings
    pool = getattr(app.state, "bot_pool", None)
    if pool is not None and getattr(pool, "size", 0) > 0:
        return pool.primary, pool
    backend = getattr(app.state, "backend", None)
    if backend and getattr(backend, "name", "") == "bot":
        return backend, pool
    if settings.bot_tokens and settings.channel_id:
        from .storage import BotBackend

        bot_backend = BotBackend(
            settings.bot_tokens[0],
            settings.channel_id,
            send_gap_s=settings.flood_send_gap_s,
            flood_budget_s=settings.flood_budget_s,
            send_timeout_s=settings.send_timeout_s,
            channel_thread_id=settings.channel_thread_id,
        )
        return bot_backend, pool
    return backend, pool


def get_ingest_storage_backend(app: Any):
    """Select chunk storage backend based on operator's tg_ingest_storage_strategy.

    - Option A (default, 0): uses configured backend (Hybrid / MTProto) for 15-25 MB/s.
    - Option B (bot_only, 1): forces chunk uploads through Bot API tokens (strict anti-ban).
    """
    db = getattr(app.state, "db", None)
    pool = getattr(app.state, "bot_pool", None)
    from . import runtime

    bot_only = bool(runtime.get_int(db, "tg_ingest_bot_only", 0)) if db is not None else False
    if bot_only:
        return get_bot_storage_backend(app)
    return app.state.backend, pool


async def send_telegram_message(
    bot_token: str,
    chat_id: int | str,
    text: str,
    reply_to_message_id: int | None = None,
) -> int | None:
    """Send a message via Telegram Bot API and return its message_id."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("result", {}).get("message_id")
            log.warning("sendMessage failed: HTTP %s: %s", resp.status_code, resp.text)
    except Exception as e:
        log.warning("sendMessage error: %s", e)
    return None


async def edit_telegram_message(
    bot_token: str,
    chat_id: int | str,
    message_id: int,
    text: str,
) -> bool:
    """Edit an existing message via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{bot_token}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            return resp.status_code == 200
    except Exception as e:
        log.warning("editMessageText error: %s", e)
    return False


class ProgressReporter:
    """Reports streaming progress, rolling speed, dynamic ETA, and progress bar to Telegram."""

    def __init__(
        self,
        bot_token: str,
        chat_id: int | str,
        message_id: int,
        filename: str,
        total_bytes: int | None,
        source_label: str = "",
        interval_s: float = 3.5,
        task_id: str | None = None,
        source: str = "telegram",
        album_context: dict[str, Any] | None = None,
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.message_id = message_id
        self.filename = filename
        self.total_bytes = total_bytes
        self.source_label = source_label
        self.interval_s = interval_s
        self.start_time = time.time()
        self.last_update_time = self.start_time
        self.task_id = task_id or uuid.uuid4().hex[:12]
        self.album_context = album_context

        existing_task = TASK_MANAGER.get(self.task_id) if (album_context and self.task_id) else None
        if existing_task:
            self.task = existing_task
            c_idx = album_context.get("current_index", 1) if album_context else 1
            t_files = album_context.get("total_files", 1) if album_context else 1
            self.task.filename = f"Album ({c_idx}/{t_files}): {filename}"
        else:
            self.task = TASK_MANAGER.create(
                task_id=self.task_id,
                source=source,
                filename=filename,
                total_bytes=total_bytes,
            )

    async def update(self, current_bytes: int) -> None:
        now = time.time()
        completed_prev = self.album_context.get("completed_bytes", 0) if self.album_context else 0
        effective_task_bytes = completed_prev + current_bytes

        if self.task:
            self.task.update_bytes(effective_task_bytes, window_s=10.0)

        if now - self.last_update_time < self.interval_s:
            return
        elapsed = now - self.start_time
        if elapsed <= 0:
            return

        speed = self.task.speed if self.task else (current_bytes / elapsed)
        speed_str = f"{format_size(speed)}/s"

        if self.album_context:
            c_idx = self.album_context.get("current_index", 1)
            t_files = self.album_context.get("total_files", 1)
            tot_album = self.album_context.get("total_album_bytes")

            if self.total_bytes and self.total_bytes > 0:
                pct = min(99.9, (current_bytes / self.total_bytes) * 100)
                rem = max(0, self.total_bytes - current_bytes)
                eta_s = rem / speed if speed > 0 else None
                eta_str = format_eta(eta_s)
                bar = render_progress_bar(pct)
                cur_sz = format_size(current_bytes)
                tot_sz = format_size(self.total_bytes)
                file_line = (
                    f"{bar} <b>{pct:.1f}%</b>\n"
                    f"📦 <b>File:</b> {cur_sz} / {tot_sz}\n"
                    f"⚡ <b>Speed:</b> {speed_str} | ⏱ <b>ETA:</b> {eta_str}"
                )
            else:
                file_line = (
                    f"📦 <b>File:</b> {format_size(current_bytes)}\n⚡ <b>Speed:</b> {speed_str}"
                )

            album_line = f"📊 <b>Completed:</b> {c_idx - 1}/{t_files} files"
            if tot_album and tot_album > 0:
                alb_pct = min(99.9, (effective_task_bytes / tot_album) * 100)
                album_line += (
                    f" ({alb_pct:.1f}%) · {format_size(effective_task_bytes)} / "
                    f"{format_size(tot_album)}"
                )

            text = (
                f"📚 <b>Album Ingest: File {c_idx}/{t_files}</b>\n"
                f"📄 <b>Current:</b> <code>{self.filename}</code>\n"
                f"{file_line}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"{album_line}"
            )
        else:
            if self.total_bytes and self.total_bytes > 0:
                pct = min(99.9, (current_bytes / self.total_bytes) * 100)
                remaining = max(0, self.total_bytes - current_bytes)
                eta_s = self.task.eta if self.task else (remaining / speed if speed > 0 else None)
                eta_str = format_eta(eta_s)
                prog_bar = render_progress_bar(pct)
                cur_sz = format_size(current_bytes)
                tot_sz = format_size(self.total_bytes)
                text = (
                    f"⏳ <b>Ingesting:</b> <code>{self.filename}</code>\n"
                    f"{prog_bar} <b>{pct:.1f}%</b>\n"
                    f"📦 <b>Size:</b> {cur_sz} / {tot_sz}\n"
                    f"⚡ <b>Speed:</b> {speed_str} | ⏱ <b>ETA:</b> {eta_str}"
                )
            else:
                text = (
                    f"⏳ <b>Ingesting:</b> <code>{self.filename}</code>\n"
                    f"📦 <b>Streamed:</b> {format_size(current_bytes)}\n"
                    f"⚡ <b>Speed:</b> {speed_str}"
                )

        self.last_update_time = now
        if self.message_id:
            await edit_telegram_message(self.bot_token, self.chat_id, self.message_id, text)


class AsyncIteratorReader:
    """Adapts an async byte iterator into an async `.read(n)` stream with cancel support."""

    def __init__(
        self,
        aiter: AsyncIterator[bytes],
        idle_timeout_s: float = 60.0,
        on_progress: Any = None,
        task: Any = None,
    ):
        self._aiter = aiter.__aiter__()
        self._buf = bytearray()
        self._eof = False
        self._timeout = idle_timeout_s
        self.bytes_read = 0
        self.on_progress = on_progress
        self.task = task

    async def read(self, n: int) -> bytes:
        if self.task and self.task.cancel_event.is_set():
            raise RuntimeError("Ingest cancelled by admin")
        while len(self._buf) < n and not self._eof:
            piece = b""
            try:
                piece = await asyncio.wait_for(self._aiter.__anext__(), timeout=self._timeout)
            except StopAsyncIteration:
                self._eof = True
            except TimeoutError as e:
                raise RuntimeError(
                    f"Download stream stalled: no bytes for {self._timeout:.0f}s"
                ) from e
            if piece:
                if self.task and self.task.cancel_event.is_set():
                    raise RuntimeError("Ingest cancelled by admin")
                self._buf.extend(piece)
                self.bytes_read += len(piece)
                if self.on_progress:
                    try:
                        await self.on_progress(self.bytes_read)
                    except Exception:
                        pass
        if not self._buf:
            return b""
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out


async def handle_bot_command(
    app: FastAPI,
    message: dict[str, Any],
    bot_token: str,
    chat_id: int | str,
    text: str,
) -> bool:
    """Handle /start, /help, /status, and /stats bot commands."""
    cmd = text.strip().split()[0].split("@")[0].lower()
    msg_id = message.get("message_id")

    if cmd in ("/start", "/help"):
        help_text = (
            "📦 <b>Anbar Ingestion Bot</b>\n\n"
            "Send or forward content to ingest it directly into Anbar:\n\n"
            "• <b>Direct Media:</b> Forward or send any media file (up to 4 GB).\n"
            "• <b>Post Links:</b> Send <code>https://t.me/c/...</code> or "
            "<code>https://t.me/...</code> for restricted channel posts.\n"
            "• <b>Web Download URLs:</b> Send direct HTTP/HTTPS download links.\n\n"
            "<b>Commands:</b>\n"
            "/cancel — Abort currently active ingest task\n"
            "/status — System telemetry & storage health\n"
            "/stats — Detailed media storage breakdown\n"
            "/help — Show this guide"
        )
        await send_telegram_message(bot_token, chat_id, help_text, reply_to_message_id=msg_id)
        return True

    if cmd in ("/cancel", "/stop"):
        active_tasks = TASK_MANAGER.list_active()
        if not active_tasks:
            await send_telegram_message(
                bot_token,
                chat_id,
                "ℹ️ <b>No active ingest tasks found.</b>",
                reply_to_message_id=msg_id,
            )
            return True

        cancelled_names = []
        for t in active_tasks:
            if TASK_MANAGER.cancel(t["id"]):
                cancelled_names.append(t.get("filename") or t["id"])

        if cancelled_names:
            names_text = "\n".join(f"• <code>{name}</code>" for name in cancelled_names)
            text = f"🛑 <b>Cancelled Ingest Task(s):</b>\n{names_text}"
        else:
            text = "ℹ️ Active tasks were already completing or finished."
        await send_telegram_message(bot_token, chat_id, text, reply_to_message_id=msg_id)
        return True

    if cmd == "/status":
        db = app.state.db
        settings = app.state.settings
        backend = getattr(app.state, "backend", None)
        backend_name = getattr(backend, "name", settings.backend.value).upper()
        bot_pool = getattr(app.state, "bot_pool", None)
        bot_count = bot_pool.size if bot_pool else len(settings.bot_tokens)

        # Check hybrid mode in SQLite runtime settings
        from . import runtime

        hyb_default = 1 if getattr(settings, "hybrid_enabled", False) else 0
        hybrid_on = bool(runtime.get_int(db, "hybrid_enabled", hyb_default))
        if hybrid_on and backend_name == "MTPROTO":
            backend_display = "HYBRID (MTProto + Bot CDN)"
        else:
            backend_display = backend_name

        ingest_mode = (
            "🛡️ Strict Bot-Only (~300-700 KB/s)"
            if bool(runtime.get_int(db, "tg_ingest_bot_only", 0))
            else "⚡ High Speed (Configured Strategy)"
        )

        # Check MTProto health
        mtproto_client = await get_active_mtproto_client(app)
        is_auth = False
        if mtproto_client:
            try:
                is_auth = await mtproto_client.is_user_authorized()
            except Exception:
                is_auth = False
        mtproto_status = "🟢 Connected & Authorized" if is_auth else "⚪ Offline / Not Auth"

        stats = db.get_system_stats() if hasattr(db, "get_system_stats") else {}
        total_objects = stats.get("total_objects", 0)
        total_bytes = stats.get("total_bytes", 0)
        total_dl = stats.get("total_downloads", 0)

        status_text = (
            "📊 <b>Anbar System Status</b>\n\n"
            f"📁 <b>Stored Objects:</b> {total_objects}\n"
            f"💾 <b>Storage Used:</b> {format_size(total_bytes)}\n"
            f"⬇️ <b>Total Downloads:</b> {total_dl}\n"
            f"⚙️ <b>Storage Backend:</b> <code>{backend_display}</code>\n"
            f"📥 <b>Ingest Upload Mode:</b> <code>{ingest_mode}</code>\n"
            f"🤖 <b>Bot Tokens in Pool:</b> {bot_count}\n"
            f"🔑 <b>MTProto Session:</b> {mtproto_status}\n"
            f"🌐 <b>Dashboard:</b> {settings.base_url}"
        )
        await send_telegram_message(bot_token, chat_id, status_text, reply_to_message_id=msg_id)
        return True

    if cmd == "/stats":
        db = app.state.db
        stats = db.get_system_stats() if hasattr(db, "get_system_stats") else {}
        bd = stats.get("breakdown", {})
        total_bytes = stats.get("total_bytes", 0)

        stats_text = (
            "📈 <b>Storage Distribution Breakdown</b>\n\n"
            f"🎬 <b>Videos:</b> {format_size(bd.get('video', 0))}\n"
            f"🎵 <b>Audio:</b> {format_size(bd.get('audio', 0))}\n"
            f"🖼️ <b>Images:</b> {format_size(bd.get('image', 0))}\n"
            f"📄 <b>Documents:</b> {format_size(bd.get('text', 0))}\n"
            f"📦 <b>Archives:</b> {format_size(bd.get('archive', 0))}\n"
            f"📁 <b>Other:</b> {format_size(bd.get('other', 0))}\n\n"
            f"📊 <b>Total:</b> {format_size(total_bytes)} ({stats.get('total_objects', 0)} files)"
        )
        await send_telegram_message(bot_token, chat_id, stats_text, reply_to_message_id=msg_id)
        return True

    return False


# Module-level album buffers & timers
ALBUM_BUFFERS: dict[str, list[dict[str, Any]]] = {}
ALBUM_TIMERS: dict[str, asyncio.Task] = {}
ALBUM_LOCK = asyncio.Lock()


async def _enqueue_album_item(app: FastAPI, message: dict[str, Any], group_id: str) -> None:
    """Debounce incoming album items sharing a media_group_id for 1.5s."""
    async with ALBUM_LOCK:
        if group_id not in ALBUM_BUFFERS:
            ALBUM_BUFFERS[group_id] = []
        ALBUM_BUFFERS[group_id].append(message)

        prev_timer = ALBUM_TIMERS.get(group_id)
        if prev_timer and not prev_timer.done():
            prev_timer.cancel()

        async def _debounced_runner() -> None:
            try:
                await asyncio.sleep(1.5)
                async with ALBUM_LOCK:
                    items = ALBUM_BUFFERS.pop(group_id, [])
                    ALBUM_TIMERS.pop(group_id, None)
                if items:
                    await _process_album_batch(app, group_id, items)
            except asyncio.CancelledError:
                pass
            except Exception as ex:
                log.exception("Error in album batch processor: %s", ex)

        ALBUM_TIMERS[group_id] = asyncio.create_task(_debounced_runner())


async def _process_album_batch(app: FastAPI, group_id: str, items: list[dict[str, Any]]) -> None:
    """Process an album batch sequentially with a unified status message."""
    settings = app.state.settings
    bot_token = settings.bot_tokens[0] if settings.bot_tokens else None
    if not bot_token or not items:
        return

    first_msg = items[0]
    chat_id = first_msg.get("chat", {}).get("id")
    reply_id = first_msg.get("message_id")
    if not chat_id:
        return

    total_files = len(items)
    extracted_media: list[dict[str, Any] | None] = [_extract_direct_media(m) for m in items]
    valid_media = [m for m in extracted_media if m is not None]
    total_album_bytes: int | None = (
        sum(m.get("size", 0) for m in valid_media) if valid_media else None
    )

    status_msg_id = await send_telegram_message(
        bot_token,
        chat_id,
        f"⏳ <b>Starting Album Ingest ({total_files} files)...</b>",
        reply_to_message_id=reply_id,
    )

    completed: list[dict[str, Any]] = []
    failed: list[tuple[str, str]] = []
    completed_bytes = 0

    album_task_id = f"alb_{group_id[:8]}"
    album_task = TASK_MANAGER.create(
        task_id=album_task_id,
        source="telegram_album",
        filename=f"Album ({total_files} files)",
        total_bytes=total_album_bytes,
    )

    for idx, (msg, media_info) in enumerate(zip(items, extracted_media, strict=True), 1):
        if album_task.cancel_event.is_set():
            album_task.state = "cancelled"
            if status_msg_id:
                cancel_text = (
                    f"❌ <b>Album Ingest Cancelled by Admin</b> "
                    f"({len(completed)}/{total_files} saved)"
                )
                await edit_telegram_message(bot_token, chat_id, status_msg_id, cancel_text)
            return

        if not media_info:
            continue

        fname = media_info["filename"]
        fsize = media_info.get("size") or 0

        album_task.filename = f"Album ({idx}/{total_files}): {fname}"

        album_ctx = {
            "current_index": idx,
            "total_files": total_files,
            "completed_bytes": completed_bytes,
            "total_album_bytes": total_album_bytes,
        }

        try:
            obj_id = await _ingest_direct_media(
                app=app,
                message=msg,
                media_info=media_info,
                bot_token=bot_token,
                chat_id=chat_id,
                status_msg_id=status_msg_id,
                task_id=album_task_id,
                album_context=album_ctx,
            )
            completed.append({"filename": fname, "size": fsize, "obj_id": obj_id})
            completed_bytes += fsize
        except Exception as ex:
            log.warning("Failed to ingest album item %s: %s", fname, ex)
            failed.append((fname, str(ex)))

    album_task.state = "done" if not failed else "error"
    base_url = settings.base_url.rstrip("/")

    if status_msg_id:
        lines = [f"✅ <b>Album Ingest Complete!</b> ({len(completed)}/{total_files} saved)\n"]
        for c in completed:
            obj_link = (
                f"{base_url}/f/{c['obj_id']}"
                if c.get("obj_id")
                else f"<code>{c['filename']}</code>"
            )
            f_hdr = f"• <code>{c['filename']}</code> ({format_size(c['size'])})"
            lines.append(f"{f_hdr}\n  🔗 {obj_link}")
        if failed:
            lines.append(f"\n⚠️ <i>{len(failed)} file(s) failed:</i>")
            for fn, err in failed:
                lines.append(f"• <code>{fn}</code>: {err[:60]}")
        await edit_telegram_message(bot_token, chat_id, status_msg_id, "\n".join(lines))


async def execute_telegram_ingest(app: FastAPI, message: dict[str, Any]) -> None:
    """Background ingestion worker processing direct media, post links, or web URLs."""
    settings = app.state.settings
    bot_token = settings.bot_tokens[0] if settings.bot_tokens else None

    chat_id = message.get("chat", {}).get("id")
    msg_id = message.get("message_id")
    text_content = message.get("text") or message.get("caption") or ""

    if not chat_id or not bot_token:
        log.warning("Cannot process ingest: missing chat_id or bot token")
        return

    # Check for Bot Commands (/start, /help, /status, /stats)
    if text_content.strip().startswith("/"):
        if await handle_bot_command(app, message, bot_token, chat_id, text_content):
            return

    # Check for Album / Media Group (multi-file forward / upload debounce)
    media_group_id = message.get("media_group_id")
    if media_group_id:
        await _enqueue_album_item(app, message, str(media_group_id))
        return

    # Check for Mode B: Protected / Restricted post link
    post_link = parse_telegram_post_link(text_content)
    # Check for Mode C: External Web URL
    web_url = parse_web_url(text_content)

    status_msg_id: int | None = None
    try:
        if post_link:
            entity, target_msg_id = post_link
            status_msg_id = await send_telegram_message(
                bot_token,
                chat_id,
                f"⏳ Ingesting post {entity}/{target_msg_id} via MTProto...",
                reply_to_message_id=msg_id,
            )
            await _ingest_protected_post(
                app=app,
                entity=entity,
                target_msg_id=target_msg_id,
                bot_token=bot_token,
                chat_id=chat_id,
                status_msg_id=status_msg_id,
            )
        elif web_url:
            status_msg_id = await send_telegram_message(
                bot_token,
                chat_id,
                f"⏳ Connecting to web URL: <code>{web_url[:60]}...</code>",
                reply_to_message_id=msg_id,
            )
            await _ingest_web_url(
                app=app,
                url=web_url,
                bot_token=bot_token,
                chat_id=chat_id,
                status_msg_id=status_msg_id,
            )
        else:
            # Mode A: Direct media attached to message
            media_info = _extract_direct_media(message)
            if not media_info:
                # No media and no link found
                await send_telegram_message(
                    bot_token,
                    chat_id,
                    "ℹ️ Please send or forward a media file (document, video, audio, photo), "
                    "a Telegram post link (<code>https://t.me/c/...</code>), "
                    "or a direct web download URL.",
                    reply_to_message_id=msg_id,
                )
                return

            filename = media_info["filename"]
            filesize = media_info["size"]

            status_msg_id = await send_telegram_message(
                bot_token,
                chat_id,
                f"⏳ Ingesting: <b>{filename}</b> ({format_size(filesize)})...",
                reply_to_message_id=msg_id,
            )

            await _ingest_direct_media(
                app=app,
                message=message,
                media_info=media_info,
                bot_token=bot_token,
                chat_id=chat_id,
                status_msg_id=status_msg_id,
            )

    except Exception as e:
        log.exception("Error in Telegram ingest worker: %s", e)
        err_msg = str(e)
        if "FloodWaitError" in type(e).__name__:
            err_msg = f"Telegram rate limit reached ({err_msg}). Please retry later."
        if status_msg_id is not None:
            await edit_telegram_message(
                bot_token,
                chat_id,
                status_msg_id,
                f"❌ <b>Ingest failed:</b> {err_msg}",
            )


def _extract_direct_media(message: dict[str, Any]) -> dict[str, Any] | None:
    """Extract file info from direct message attachment."""
    if "document" in message:
        doc = message["document"]
        fid = doc.get("file_id")
        fname = doc.get("file_name") or f"doc_{fid[:8]}.bin"
        return {
            "file_id": fid,
            "filename": fname,
            "size": doc.get("file_size", 0),
            "content_type": doc.get("mime_type") or "application/octet-stream",
            "type": "document",
            "doc": doc,
        }
    if "video" in message:
        vid = message["video"]
        fid = vid.get("file_id")
        fname = vid.get("file_name") or f"video_{fid[:8]}.mp4"
        return {
            "file_id": fid,
            "filename": fname,
            "size": vid.get("file_size", 0),
            "content_type": vid.get("mime_type") or "video/mp4",
            "type": "video",
            "doc": vid,
        }
    if "audio" in message:
        aud = message["audio"]
        fid = aud.get("file_id")
        fname = aud.get("file_name") or f"audio_{fid[:8]}.mp3"
        return {
            "file_id": fid,
            "filename": fname,
            "size": aud.get("file_size", 0),
            "content_type": aud.get("mime_type") or "audio/mpeg",
            "type": "audio",
            "doc": aud,
        }
    if "photo" in message and isinstance(message["photo"], list) and message["photo"]:
        best = message["photo"][-1]
        fid = best.get("file_id")
        return {
            "file_id": fid,
            "filename": f"photo_{fid[:8]}.jpg",
            "size": best.get("file_size", 0),
            "content_type": "image/jpeg",
            "type": "photo",
            "doc": best,
        }
    return None


async def _ingest_direct_media(
    app: FastAPI,
    message: dict[str, Any],
    media_info: dict[str, Any],
    bot_token: str,
    chat_id: int | str,
    status_msg_id: int | None,
    task_id: str | None = None,
    album_context: dict[str, Any] | None = None,
) -> str | None:
    """Mode A: Ingest direct media via Bot API getFile, falling back to MTProto for >20MB."""
    settings = app.state.settings
    db = app.state.db
    # Chunk storage backend: respects tg_ingest_storage_strategy (configured vs bot_only)
    backend, pool = get_ingest_storage_backend(app)

    file_id = media_info["file_id"]
    filename = media_info["filename"]
    filesize = media_info.get("size") or 0
    content_type = media_info["content_type"]

    use_bot_api = filesize <= 20 * 1024 * 1024
    bot_api_file_path = None

    if use_bot_api:
        get_file_url = f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(get_file_url)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    bot_api_file_path = data.get("result", {}).get("file_path")
            elif resp.status_code == 400 and "file is too big" in resp.text:
                log.info("Bot API getFile: file is too big -> falling back to MTProto")
                use_bot_api = False

    if use_bot_api and bot_api_file_path:
        download_url = f"https://api.telegram.org/file/bot{bot_token}/{bot_api_file_path}"
        reporter = (
            ProgressReporter(
                bot_token,
                chat_id,
                status_msg_id or 0,
                filename,
                filesize,
                task_id=task_id,
                album_context=album_context,
            )
            if (status_msg_id or task_id)
            else None
        )

        async with httpx.AsyncClient(timeout=settings.ingest_read_timeout_s) as dl_client:
            async with dl_client.stream("GET", download_url) as stream_resp:
                if stream_resp.status_code != 200:
                    raise RuntimeError(f"Failed to stream file: HTTP {stream_resp.status_code}")

                reader = AsyncIteratorReader(
                    stream_resp.aiter_bytes(256 * 1024),
                    idle_timeout_s=settings.body_idle_timeout_s,
                    on_progress=reporter.update if reporter else None,
                    task=reporter.task if reporter else None,
                )
                service = ObjectService(
                    backend=backend,
                    db=db,
                    settings=settings,
                    filename=filename,
                    content_type=content_type,
                    pool=pool,
                )
                try:
                    manifest, sha_hex = await service.store_stream(reader)
                except BaseException:
                    if reporter and reporter.task:
                        reporter.task.state = (
                            "cancelled" if reporter.task.cancel_event.is_set() else "error"
                        )
                    await service.rollback()
                    raise

                obj_id = service.commit(sha_hex=sha_hex, uploader_key="tg_webhook")
                service.drop_checkpoint()
                if reporter and reporter.task:
                    reporter.task.state = "done"

                _schedule_post_commit_tasks(settings, obj_id, content_type, filename, service)

                base_url = settings.base_url.rstrip("/")
                success_text = (
                    f"✅ <b>Saved to Anbar!</b>\n\n"
                    f"📁 <b>Name:</b> <code>{filename}</code>\n"
                    f"📦 <b>Size:</b> {format_size(manifest.total_size)}\n"
                    f"🔗 <b>Link:</b> {base_url}/f/{obj_id}"
                )
                if not album_context and status_msg_id is not None:
                    await edit_telegram_message(bot_token, chat_id, status_msg_id, success_text)
                return obj_id

    # Fallback to MTProto for large files (> 20MB)
    fwd_chat = message.get("forward_from_chat")
    fwd_msg_id = message.get("forward_from_message_id")
    if fwd_chat and fwd_chat.get("id") and fwd_msg_id:
        return await _ingest_protected_post(
            app=app,
            entity=fwd_chat["id"],
            target_msg_id=fwd_msg_id,
            bot_token=bot_token,
            chat_id=chat_id,
            status_msg_id=status_msg_id,
            task_id=task_id,
            album_context=album_context,
        )

    mtproto_client = await get_active_mtproto_client(app)
    if mtproto_client is None:
        raise RuntimeError(
            "File exceeds 20MB Bot API limit and MTProto client is not authenticated. "
            "Please configure MTProto or send a channel post link (https://t.me/c/...)."
        )

    # Search user's chat with bot
    bot_id = int(bot_token.split(":")[0])
    try:
        recent_msgs = await mtproto_client.get_messages(bot_id, limit=5)
    except Exception as e:
        raise RuntimeError(f"Could not retrieve messages via MTProto: {e}") from e

    target_msg = next((m for m in recent_msgs if getattr(m, "media", None)), None)
    if not target_msg:
        raise RuntimeError(
            "File exceeds 20MB Bot API limit. Please forward from a channel or "
            "send the channel post link (https://t.me/c/...) so MTProto can stream it."
        )

    return await _stream_telethon_media(
        app=app,
        mtproto_client=mtproto_client,
        media=target_msg.media,
        filename=filename,
        filesize=filesize,
        content_type=content_type,
        bot_token=bot_token,
        chat_id=chat_id,
        status_msg_id=status_msg_id,
        task_id=task_id,
        album_context=album_context,
    )


async def _ingest_protected_post(
    app: FastAPI,
    entity: int | str,
    target_msg_id: int,
    bot_token: str,
    chat_id: int | str,
    status_msg_id: int | None,
    task_id: str | None = None,
    album_context: dict[str, Any] | None = None,
) -> str | None:
    """Mode B: Ingest restricted/protected channel media via Telethon MTProto client."""
    mtproto_client = await get_active_mtproto_client(app)
    if mtproto_client is None:
        raise RuntimeError(
            "MTProto client is not active or authorized. "
            "Please configure ANBAR_API_ID, ANBAR_API_HASH, and a valid session."
        )

    try:
        msg = await mtproto_client.get_messages(entity, ids=target_msg_id)
    except Exception as e:
        raise RuntimeError(f"Could not fetch message {target_msg_id} from {entity}: {e}") from e

    if not msg:
        raise RuntimeError(f"Message {target_msg_id} not found in {entity}")
    if not getattr(msg, "media", None):
        raise RuntimeError(f"Message {target_msg_id} does not contain any downloadable media")

    filename = getattr(msg, "file", None) and getattr(msg.file, "name", None)
    content_type = getattr(msg, "file", None) and getattr(msg.file, "mime_type", None)
    filesize = getattr(msg, "file", None) and getattr(msg.file, "size", None)

    if not filename:
        ext = (getattr(msg, "file", None) and getattr(msg.file, "ext", None)) or ".bin"
        filename = f"post_{target_msg_id}{ext}"
    if not content_type:
        content_type = "application/octet-stream"

    return await _stream_telethon_media(
        app=app,
        mtproto_client=mtproto_client,
        media=msg.media,
        filename=filename,
        filesize=filesize,
        content_type=content_type,
        bot_token=bot_token,
        chat_id=chat_id,
        status_msg_id=status_msg_id,
        task_id=task_id,
        album_context=album_context,
    )


async def _stream_telethon_media(
    app: FastAPI,
    mtproto_client: Any,
    media: Any,
    filename: str,
    filesize: int | None,
    content_type: str,
    bot_token: str,
    chat_id: int | str,
    status_msg_id: int | None,
    task_id: str | None = None,
    album_context: dict[str, Any] | None = None,
) -> str | None:
    """Download chunks from Telethon MTProto and upload to Anbar via Bot Tokens."""
    settings = app.state.settings
    db = app.state.db
    # Chunk storage backend: respects tg_ingest_storage_strategy (configured vs bot_only)
    backend, pool = get_ingest_storage_backend(app)

    reporter = (
        ProgressReporter(
            bot_token,
            chat_id,
            status_msg_id or 0,
            filename,
            filesize,
            task_id=task_id,
            album_context=album_context,
        )
        if (status_msg_id or task_id)
        else None
    )

    async def _resilient_telethon_iter():
        offset = 0
        max_retries = 10
        retries = 0
        total_expected = filesize or 0

        while total_expected == 0 or offset < total_expected:
            try:
                # Telethon continuous streaming from current offset
                async for chunk in mtproto_client.iter_download(
                    media,
                    offset=offset,
                    request_size=512 * 1024,
                ):
                    if not chunk:
                        continue
                    offset += len(chunk)
                    retries = 0
                    yield chunk

                break
            except Exception as e:
                # Account safety: respect FloodWait unconditionally
                if "FloodWait" in type(e).__name__:
                    wait_s = int(getattr(e, "seconds", 10))
                    log.warning("Telethon download FloodWait: sleeping %s seconds", wait_s)
                    await asyncio.sleep(wait_s + 1)
                    continue

                retries += 1
                if retries > max_retries:
                    log.error(
                        "Telethon download failed at offset %d after %d retries: %s",
                        offset,
                        max_retries,
                        e,
                    )
                    raise

                backoff = min(10.0, 1.0 * (1.5**retries))
                log.warning(
                    "Telethon download stalled at %s (offset %d): %s. "
                    "Resuming in %.1fs (retry %d/%d)...",
                    format_size(offset),
                    offset,
                    e,
                    backoff,
                    retries,
                    max_retries,
                )
                await asyncio.sleep(backoff)
                try:
                    if not mtproto_client.is_connected():
                        await mtproto_client.connect()
                except Exception as conn_err:
                    log.debug("Telethon reconnect attempt notice: %s", conn_err)

    async def _pipelined_telethon_iter():
        # Buffer up to 32 slices (16MB) to overlap continuous MTProto with Bot CDN uploads
        queue: asyncio.Queue[bytes | Exception | None] = asyncio.Queue(maxsize=32)

        async def _producer() -> None:
            try:
                async for chunk in _resilient_telethon_iter():
                    await queue.put(chunk)
            except Exception as ex:
                await queue.put(ex)
            finally:
                await queue.put(None)

        prod_task = asyncio.create_task(_producer())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            if not prod_task.done():
                prod_task.cancel()

    async def _fast_telethon_iter():
        """Fast parallel chunk streaming via low-level upload.GetFileRequest pipelining.

        Achieves 5-15+ MB/s on a single user account by keeping 4 concurrent 512KB slice
        requests in flight simultaneously over the DC sender. Reassembles chunks in strict
        sequential order in memory with a bounded 8MB buffer.
        """
        part_size = 512 * 1024
        total_expected = filesize or 0

        # 1. Resolve location and DC info
        file_info = None
        location = None
        dc_id = None
        try:
            from telethon import utils

            file_info = utils._get_file_info(media)
            if file_info:
                dc_id = file_info.dc_id
                location = file_info.location
                if not total_expected:
                    total_expected = file_info.size or 0
        except Exception as ex:
            log.warning("Could not extract MTProto file location: %s", ex)

        # Fallback to single-stream pipeline if location cannot be resolved or file <= 1MB
        if not location or total_expected <= 2 * part_size:
            async for chunk in _pipelined_telethon_iter():
                yield chunk
            return

        # 2. Acquire MTProto sender for the target DC
        exported = False
        sender = None
        try:
            from telethon import errors

            if dc_id and mtproto_client.session.dc_id != dc_id:
                try:
                    sender = await mtproto_client._borrow_exported_sender(dc_id)
                    exported = True
                except errors.DcIdInvalidError:
                    sender = mtproto_client._sender
                    exported = False
            else:
                sender = mtproto_client._sender
        except Exception as ex:
            log.warning(
                "Could not borrow sender for DC %s: %s; falling back to single stream",
                dc_id,
                ex,
            )
            async for chunk in _pipelined_telethon_iter():
                yield chunk
            return

        total_parts = (total_expected + part_size - 1) // part_size
        num_workers = min(4, total_parts)
        next_part = 0
        part_lock = asyncio.Lock()
        queue: asyncio.Queue[tuple[int, bytes] | Exception] = asyncio.Queue(maxsize=16)
        stop_event = asyncio.Event()

        from telethon import functions

        async def _worker() -> None:
            nonlocal next_part, sender, exported
            while not stop_event.is_set():
                async with part_lock:
                    if next_part >= total_parts:
                        break
                    p_idx = next_part
                    next_part += 1

                offset = p_idx * part_size
                retries = 0
                max_retries = 10

                while not stop_event.is_set():
                    try:
                        req = functions.upload.GetFileRequest(
                            location=location,
                            offset=offset,
                            limit=part_size,
                            precise=True,
                            cdn_supported=False,
                        )
                        res = await mtproto_client._call(sender, req)
                        data = getattr(res, "bytes", b"")
                        await queue.put((p_idx, data))
                        break
                    except Exception as e:
                        if "FloodWait" in type(e).__name__:
                            wait_s = int(getattr(e, "seconds", 10))
                            log.warning(
                                "FastTelethon download FloodWait: sleeping %s seconds",
                                wait_s,
                            )
                            await asyncio.sleep(wait_s + 1)
                            continue
                        if "FileMigrate" in type(e).__name__:
                            new_dc = getattr(e, "new_dc", None)
                            if new_dc:
                                try:
                                    old_sender = sender
                                    sender = await mtproto_client._borrow_exported_sender(new_dc)
                                    if exported and old_sender != mtproto_client._sender:
                                        await mtproto_client._return_exported_sender(old_sender)
                                    exported = True
                                    continue
                                except Exception as mig_err:
                                    log.debug("FileMigrate sender switch failed: %s", mig_err)

                        retries += 1
                        if retries > max_retries:
                            log.error(
                                "FastTelethon worker failed on part %d (offset %d): %s",
                                p_idx,
                                offset,
                                e,
                            )
                            await queue.put(e)
                            return
                        backoff = min(10.0, 1.0 * (1.5**retries))
                        await asyncio.sleep(backoff)
                        if not mtproto_client.is_connected():
                            try:
                                await mtproto_client.connect()
                            except Exception:
                                pass

        workers = [asyncio.create_task(_worker()) for _ in range(num_workers)]

        async def _sentinel() -> None:
            await asyncio.gather(*workers, return_exceptions=True)
            await queue.put((-1, b""))

        sentinel_task = asyncio.create_task(_sentinel())
        expected_part = 0
        reorder_buf: dict[int, bytes] = {}

        try:
            while expected_part < total_parts:
                while expected_part in reorder_buf:
                    yield reorder_buf.pop(expected_part)
                    expected_part += 1
                if expected_part >= total_parts:
                    break

                item = await queue.get()
                if isinstance(item, Exception):
                    raise item
                p_idx, data = item
                if p_idx == -1:
                    break
                reorder_buf[p_idx] = data
                while expected_part in reorder_buf:
                    yield reorder_buf.pop(expected_part)
                    expected_part += 1
        finally:
            stop_event.set()
            for w in workers:
                w.cancel()
            sentinel_task.cancel()
            if exported and sender and sender != mtproto_client._sender:
                try:
                    await mtproto_client._return_exported_sender(sender)
                except Exception:
                    pass

    reader = AsyncIteratorReader(
        _fast_telethon_iter(),
        idle_timeout_s=settings.body_idle_timeout_s,
        on_progress=reporter.update if reporter else None,
        task=reporter.task if reporter else None,
    )
    service = ObjectService(
        backend=backend,
        db=db,
        settings=settings,
        filename=filename,
        content_type=content_type,
        pool=pool,
    )
    try:
        manifest, sha_hex = await service.store_stream(reader)
    except BaseException:
        if reporter and reporter.task:
            reporter.task.state = "cancelled" if reporter.task.cancel_event.is_set() else "error"
        await service.rollback()
        raise

    obj_id = service.commit(sha_hex=sha_hex, uploader_key="tg_webhook_mtproto")
    service.drop_checkpoint()
    if reporter and reporter.task:
        reporter.task.state = "done"

    _schedule_post_commit_tasks(settings, obj_id, content_type, filename, service)

    base_url = settings.base_url.rstrip("/")
    success_text = (
        f"✅ <b>Saved to Anbar!</b>\n\n"
        f"📁 <b>Name:</b> <code>{filename}</code>\n"
        f"📦 <b>Size:</b> {format_size(manifest.total_size)}\n"
        f"🔗 <b>Link:</b> {base_url}/f/{obj_id}"
    )
    if not album_context and status_msg_id is not None:
        await edit_telegram_message(bot_token, chat_id, status_msg_id, success_text)
    return obj_id


async def _ingest_web_url(
    app: FastAPI,
    url: str,
    bot_token: str,
    chat_id: int | str,
    status_msg_id: int | None,
    task_id: str | None = None,
) -> None:
    """Mode C: Stream an external web URL into Anbar using the configured storage strategy."""
    settings = app.state.settings
    db = app.state.db
    # External URLs use the configured storage strategy in Settings
    backend = app.state.backend
    pool = getattr(app.state, "bot_pool", None)

    async with httpx.AsyncClient(timeout=settings.ingest_read_timeout_s) as client:
        async with client.stream("GET", url, follow_redirects=True) as resp:
            if resp.status_code >= 400:
                raise RuntimeError(f"Origin returned HTTP {resp.status_code}")

            filename = _filename_from_url(str(resp.url), resp.headers)
            content_type = _guess_content_type(resp.headers, "application/octet-stream")
            cl_header = resp.headers.get("content-length")
            total_bytes = int(cl_header) if cl_header and cl_header.isdigit() else None

            reporter = (
                ProgressReporter(
                    bot_token,
                    chat_id,
                    status_msg_id or 0,
                    filename,
                    total_bytes,
                    task_id=task_id,
                    source="url",
                )
                if (status_msg_id or task_id)
                else None
            )

            reader = AsyncIteratorReader(
                resp.aiter_bytes(256 * 1024),
                idle_timeout_s=settings.body_idle_timeout_s,
                on_progress=reporter.update if reporter else None,
                task=reporter.task if reporter else None,
            )
            service = ObjectService(
                backend=backend,
                db=db,
                settings=settings,
                filename=filename,
                content_type=content_type,
                pool=pool,
            )
            try:
                manifest, sha_hex = await service.store_stream(reader)
            except BaseException:
                if reporter and reporter.task:
                    reporter.task.state = (
                        "cancelled" if reporter.task.cancel_event.is_set() else "error"
                    )
                await service.rollback()
                raise

            obj_id = service.commit(sha_hex=sha_hex, uploader_key="tg_webhook_url")
            service.drop_checkpoint()
            if reporter and reporter.task:
                reporter.task.state = "done"

            _schedule_post_commit_tasks(settings, obj_id, content_type, filename, service)

            base_url = settings.base_url.rstrip("/")
            success_text = (
                f"✅ <b>Saved to Anbar!</b>\n\n"
                f"📁 <b>Name:</b> <code>{filename}</code>\n"
                f"📦 <b>Size:</b> {format_size(manifest.total_size)}\n"
                f"🔗 <b>Link:</b> {base_url}/f/{obj_id}"
            )
            if status_msg_id is not None:
                await edit_telegram_message(bot_token, chat_id, status_msg_id, success_text)


def _schedule_post_commit_tasks(
    settings: Any,
    obj_id: str,
    content_type: str | None,
    filename: str,
    service: ObjectService,
) -> None:
    """Best-effort background tasks: thumbnails & subtitle extraction."""
    from . import thumbs

    if service.first_chunk and content_type and thumbs.SUPPORTED_OK(content_type):

        async def _make_thumb() -> None:
            try:
                await thumbs.generate(settings, obj_id, content_type, service.first_chunk)
            except Exception:
                pass

        spawn_background_task(_make_thumb(), name=f"tg_ingest:thumb:{obj_id}")

    from . import subs_extract

    if subs_extract.AVAILABLE and subs_extract.video_ext(filename):

        async def _extract_subs() -> None:
            try:
                pass
            except Exception:
                pass

        spawn_background_task(_extract_subs(), name=f"tg_ingest:subs:{obj_id}")
