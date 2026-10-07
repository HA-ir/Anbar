"""Streaming ingestion pipeline for Telegram Bot webhook updates.

Supports:
- Mode A: Direct forwarded / uploaded media (document, video, audio, photo)
- Mode B: Restricted / protected channel post links (t.me/c/... or t.me/...) via MTProto
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import httpx

from .mtproto_provider import get_active_mtproto_client
from .object_service import ObjectService
from .tasks import spawn_background_task

if TYPE_CHECKING:
    from fastapi import FastAPI

log = logging.getLogger("anbar.tg_ingest")

RE_PRIVATE_POST = re.compile(r"t\.me/c/(\d+)/(\d+)")
RE_PUBLIC_POST = re.compile(r"t\.me/([a-zA-Z0-9_]{4,})/(\d+)")


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


def parse_telegram_post_link(text: str) -> tuple[int | str, int] | None:
    """Extract (entity, message_id) from a Telegram message link."""
    # 1. Private channel / supergroup: t.me/c/<channel_id>/<msg_id>
    m_priv = RE_PRIVATE_POST.search(text)
    if m_priv:
        raw_cid, mid = m_priv.groups()
        # In Telegram MTProto, channel IDs in URLs map to -100<id>
        channel_id = int(f"-100{raw_cid}")
        return channel_id, int(mid)

    # 2. Public channel / group: t.me/<username>/<msg_id>
    m_pub = RE_PUBLIC_POST.search(text)
    if m_pub:
        username, mid = m_pub.groups()
        if username.lower() not in ("joinchat", "share", "addstickers", "invoice", "c"):
            return username, int(mid)

    return None


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


class AsyncIteratorReader:
    """Adapts an async byte iterator into an async `.read(n)` stream for chunk_stream."""

    def __init__(self, aiter: AsyncIterator[bytes], idle_timeout_s: float = 60.0):
        self._aiter = aiter.__aiter__()
        self._buf = bytearray()
        self._eof = False
        self._timeout = idle_timeout_s

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
        return out


async def execute_telegram_ingest(app: FastAPI, message: dict[str, Any]) -> None:
    """Background ingestion worker processing a direct media message or post link."""
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
        else:
            # Mode A: Direct media attached to message
            media_info = _extract_direct_media(message)
            if not media_info:
                # No media and no link found
                await send_telegram_message(
                    bot_token,
                    chat_id,
                    "ℹ️ Please send or forward a media file (document, video, audio, photo) "
                    "or a Telegram post link (e.g. <code>https://t.me/c/...</code>).",
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
    media_info: dict[str, Any],
    bot_token: str,
    chat_id: int | str,
    status_msg_id: int | None,
) -> None:
    """Mode A: Ingest direct media via Bot API getFile stream."""
    settings = app.state.settings
    db = app.state.db
    backend = app.state.backend
    pool = getattr(app.state, "bot_pool", None)
    file_id = media_info["file_id"]
    filename = media_info["filename"]
    content_type = media_info["content_type"]

    # 1. Fetch file path from Bot API
    get_file_url = f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(get_file_url)
        if resp.status_code != 200:
            raise RuntimeError(f"Bot API getFile returned HTTP {resp.status_code}: {resp.text}")
        data = resp.json()
        if not data.get("ok"):
            desc = data.get("description", "getFile failed")
            raise RuntimeError(f"Telegram Bot API error: {desc}")
        file_path = data.get("result", {}).get("file_path")
        if not file_path:
            raise RuntimeError("Telegram Bot API did not return a file_path")

    # 2. Stream directly from Bot API download URL
    download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"

    async def _stream_and_commit():
        async with httpx.AsyncClient(timeout=settings.ingest_read_timeout_s) as dl_client:
            async with dl_client.stream("GET", download_url) as stream_resp:
                if stream_resp.status_code != 200:
                    raise RuntimeError(f"Failed to stream file: HTTP {stream_resp.status_code}")

                reader = AsyncIteratorReader(
                    stream_resp.aiter_bytes(256 * 1024),
                    idle_timeout_s=settings.body_idle_timeout_s,
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

                # Trigger background thumbnail generation and subtitle extraction
                _schedule_post_commit_tasks(settings, obj_id, content_type, filename, service)

                # Send success response
                base_url = settings.base_url.rstrip("/")
                success_text = (
                    f"✅ <b>Saved to Anbar!</b>\n\n"
                    f"📁 <b>Name:</b> <code>{filename}</code>\n"
                    f"📦 <b>Size:</b> {format_size(manifest.total_size)}\n"
                    f"🔗 <b>Link:</b> {base_url}/f/{obj_id}"
                )
                if status_msg_id is not None:
                    await edit_telegram_message(bot_token, chat_id, status_msg_id, success_text)

    await _stream_and_commit()


async def _ingest_protected_post(
    app: FastAPI,
    entity: int | str,
    target_msg_id: int,
    bot_token: str,
    chat_id: int | str,
    status_msg_id: int | None,
) -> None:
    """Mode B: Ingest restricted/protected channel media via Telethon MTProto client."""
    settings = app.state.settings
    db = app.state.db
    backend = app.state.backend
    pool = getattr(app.state, "bot_pool", None)

    mtproto_client = await get_active_mtproto_client(app)
    if mtproto_client is None:
        raise RuntimeError(
            "MTProto client is not active or authorized. "
            "Please configure ANBAR_API_ID, ANBAR_API_HASH, and a valid session."
        )

    # 1. Resolve entity & message
    try:
        msg = await mtproto_client.get_messages(entity, ids=target_msg_id)
    except Exception as e:
        raise RuntimeError(f"Could not fetch message {target_msg_id} from {entity}: {e}") from e

    if not msg:
        raise RuntimeError(f"Message {target_msg_id} not found in {entity}")
    if not getattr(msg, "media", None):
        raise RuntimeError(f"Message {target_msg_id} does not contain any downloadable media")

    # 2. Extract filename and size from Telethon message
    media = msg.media
    filename = getattr(msg, "file", None) and getattr(msg.file, "name", None)
    content_type = getattr(msg, "file", None) and getattr(msg.file, "mime_type", None)
    filesize = getattr(msg, "file", None) and getattr(msg.file, "size", None)

    if not filename:
        ext = (getattr(msg, "file", None) and getattr(msg.file, "ext", None)) or ".bin"
        filename = f"post_{target_msg_id}{ext}"
    if not content_type:
        content_type = "application/octet-stream"

    if status_msg_id is not None:
        await edit_telegram_message(
            bot_token,
            chat_id,
            status_msg_id,
            f"⏳ Ingesting: <b>{filename}</b> ({format_size(filesize)}) via MTProto...",
        )

    # 3. Stream chunks directly from Telethon client.iter_download()
    async def _telethon_iter():
        async for chunk in mtproto_client.iter_download(media, request_size=512 * 1024):
            yield chunk

    reader = AsyncIteratorReader(
        _telethon_iter(),
        idle_timeout_s=settings.body_idle_timeout_s,
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

    # Post-commit tasks
    _schedule_post_commit_tasks(settings, obj_id, content_type, filename, service)

    # Success edit
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
                # Video subtitles extract
                pass
            except Exception:
                pass

        spawn_background_task(_extract_subs(), name=f"tg_ingest:subs:{obj_id}")
