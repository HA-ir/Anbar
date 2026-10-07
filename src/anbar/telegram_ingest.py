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
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import httpx

from .api.ingest import _filename_from_url, _guess_content_type
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
    """Reports streaming progress, speed, ETA, and progress bar to Telegram."""

    def __init__(
        self,
        bot_token: str,
        chat_id: int | str,
        message_id: int,
        filename: str,
        total_bytes: int | None,
        source_label: str,
        interval_s: float = 3.5,
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

    async def update(self, current_bytes: int) -> None:
        now = time.time()
        if now - self.last_update_time < self.interval_s:
            return
        elapsed = now - self.start_time
        if elapsed <= 0:
            return
        speed = current_bytes / elapsed
        speed_str = f"{format_size(speed)}/s"

        if self.total_bytes and self.total_bytes > 0:
            pct = min(99.9, (current_bytes / self.total_bytes) * 100)
            remaining = max(0, self.total_bytes - current_bytes)
            eta_s = remaining / speed if speed > 0 else None
            eta_str = format_eta(eta_s)
            prog_bar = render_progress_bar(pct)
            text = (
                f"⏳ <b>Ingesting:</b> <code>{self.filename}</code>\n"
                f"{prog_bar} <b>{pct:.1f}%</b>\n"
                f"📦 <b>Size:</b> {format_size(current_bytes)} / {format_size(self.total_bytes)}\n"
                f"⚡ <b>Speed:</b> {speed_str} | ⏱ <b>ETA:</b> {eta_str}\n"
                f"🛡️ <b>Path:</b> {self.source_label}"
            )
        else:
            text = (
                f"⏳ <b>Ingesting:</b> <code>{self.filename}</code>\n"
                f"📦 <b>Streamed:</b> {format_size(current_bytes)}\n"
                f"⚡ <b>Speed:</b> {speed_str}\n"
                f"🛡️ <b>Path:</b> {self.source_label}"
            )

        self.last_update_time = now
        await edit_telegram_message(self.bot_token, self.chat_id, self.message_id, text)


class AsyncIteratorReader:
    """Adapts an async byte iterator into an async `.read(n)` stream with progress hooks."""

    def __init__(
        self,
        aiter: AsyncIterator[bytes],
        idle_timeout_s: float = 60.0,
        on_progress: Any = None,
    ):
        self._aiter = aiter.__aiter__()
        self._buf = bytearray()
        self._eof = False
        self._timeout = idle_timeout_s
        self.bytes_read = 0
        self.on_progress = on_progress

    async def read(self, n: int) -> bytes:
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
                self._buf.extend(piece)
        if not self._buf:
            return b""
        out = bytes(self._buf[:n])
        del self._buf[:n]
        self.bytes_read += len(out)
        if self.on_progress:
            try:
                await self.on_progress(self.bytes_read)
            except Exception:
                pass
        return out


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
) -> None:
    """Mode A: Ingest direct media via Bot API getFile, falling back to MTProto for >20MB."""
    settings = app.state.settings
    db = app.state.db
    # Anti-ban routing: chunk uploads to Anbar storage strictly use Bot tokens
    backend, pool = get_bot_storage_backend(app)

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
                status_msg_id,
                filename,
                filesize,
                "Bot API ➔ Bot CDN",
            )
            if status_msg_id
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
                )
                service = ObjectService(
                    backend=backend,
                    db=db,
                    settings=settings,
                    filename=filename,
                    content_type=content_type,
                    pool=pool,
                )
                manifest, sha_hex = await service.store_stream(reader)
                obj_id = service.commit(sha_hex=sha_hex, uploader_key="tg_webhook")
                service.drop_checkpoint()

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
                return

    # Fallback to MTProto for large files (> 20MB)
    fwd_chat = message.get("forward_from_chat")
    fwd_msg_id = message.get("forward_from_message_id")
    if fwd_chat and fwd_chat.get("id") and fwd_msg_id:
        await _ingest_protected_post(
            app=app,
            entity=fwd_chat["id"],
            target_msg_id=fwd_msg_id,
            bot_token=bot_token,
            chat_id=chat_id,
            status_msg_id=status_msg_id,
        )
        return

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

    await _stream_telethon_media(
        app=app,
        mtproto_client=mtproto_client,
        media=target_msg.media,
        filename=filename,
        filesize=filesize,
        content_type=content_type,
        bot_token=bot_token,
        chat_id=chat_id,
        status_msg_id=status_msg_id,
    )


async def _ingest_protected_post(
    app: FastAPI,
    entity: int | str,
    target_msg_id: int,
    bot_token: str,
    chat_id: int | str,
    status_msg_id: int | None,
) -> None:
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

    await _stream_telethon_media(
        app=app,
        mtproto_client=mtproto_client,
        media=msg.media,
        filename=filename,
        filesize=filesize,
        content_type=content_type,
        bot_token=bot_token,
        chat_id=chat_id,
        status_msg_id=status_msg_id,
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
) -> None:
    """Download chunks from Telethon MTProto and upload to Anbar via Bot Tokens."""
    settings = app.state.settings
    db = app.state.db
    # Anti-ban routing: chunk uploads to Anbar storage strictly use Bot tokens
    backend, pool = get_bot_storage_backend(app)

    reporter = (
        ProgressReporter(
            bot_token,
            chat_id,
            status_msg_id,
            filename,
            filesize,
            "MTProto Download ➔ Bot CDN Storage",
        )
        if status_msg_id
        else None
    )

    async def _telethon_iter():
        async for chunk in mtproto_client.iter_download(media, request_size=512 * 1024):
            yield chunk

    reader = AsyncIteratorReader(
        _telethon_iter(),
        idle_timeout_s=settings.body_idle_timeout_s,
        on_progress=reporter.update if reporter else None,
    )
    service = ObjectService(
        backend=backend,
        db=db,
        settings=settings,
        filename=filename,
        content_type=content_type,
        pool=pool,
    )
    manifest, sha_hex = await service.store_stream(reader)
    obj_id = service.commit(sha_hex=sha_hex, uploader_key="tg_webhook_mtproto")
    service.drop_checkpoint()

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


async def _ingest_web_url(
    app: FastAPI,
    url: str,
    bot_token: str,
    chat_id: int | str,
    status_msg_id: int | None,
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
                    status_msg_id,
                    filename,
                    total_bytes,
                    f"Web URL ➔ {getattr(backend, 'name', 'storage').upper()}",
                )
                if status_msg_id
                else None
            )

            reader = AsyncIteratorReader(
                resp.aiter_bytes(256 * 1024),
                idle_timeout_s=settings.body_idle_timeout_s,
                on_progress=reporter.update if reporter else None,
            )
            service = ObjectService(
                backend=backend,
                db=db,
                settings=settings,
                filename=filename,
                content_type=content_type,
                pool=pool,
            )
            manifest, sha_hex = await service.store_stream(reader)
            obj_id = service.commit(sha_hex=sha_hex, uploader_key="tg_webhook_url")
            service.drop_checkpoint()

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
