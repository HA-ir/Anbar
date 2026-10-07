"""Shared MTProto client provider for background tasks & telegram webhook.

Provides an active Telethon TelegramClient whether the primary storage backend
is MTProto or Bot.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from telethon import TelegramClient

log = logging.getLogger("anbar.mtproto_provider")


async def get_active_mtproto_client(app: Any) -> TelegramClient | None:
    """Retrieve or initialize an active, connected Telethon client."""
    # 1. Reuse primary storage backend client if running Backend.MTPROTO
    backend = getattr(app.state, "backend", None)
    if backend and getattr(backend, "name", "") == "mtproto":
        client = getattr(backend, "_client", None)
        if client and getattr(backend, "_connected", False):
            return client

    # 2. Reuse already-instantiated helper on app.state
    helper = getattr(app.state, "mtproto_helper", None)
    if helper is not None:
        try:
            if helper.is_connected():
                return helper
            await helper.connect()
            if await helper.is_user_authorized():
                return helper
        except Exception as e:
            log.warning("Existing mtproto_helper connection check failed: %s", e)

    # 3. Check configuration & session storage
    settings = getattr(app.state, "settings", None)
    db = getattr(app.state, "db", None)
    if not settings or not db:
        return None

    api_id = settings.api_id
    api_hash = settings.api_hash
    if not api_id or not api_hash:
        return None

    from telethon import TelegramClient

    raw_session = db.kv_get("cfg_tg_session")
    client_inst: TelegramClient | None = None

    if raw_session:
        from telethon.sessions import StringSession

        client_inst = TelegramClient(StringSession(raw_session), int(api_id), str(api_hash))
    elif settings.session_file and settings.session_file.exists():
        client_inst = TelegramClient(str(settings.session_file), int(api_id), str(api_hash))

    if client_inst is None:
        return None

    try:
        await client_inst.connect()
        if await client_inst.is_user_authorized():
            app.state.mtproto_helper = client_inst
            return client_inst
        log.warning("MTProto client connected but user is not authorized")
        await client_inst.disconnect()
        return None
    except Exception as e:
        log.warning("Failed to connect auxiliary MTProto client: %s", e)
        return None


async def close_mtproto_helper(app: Any) -> None:
    """Disconnect and clean up any auxiliary MTProto client on shutdown."""
    helper = getattr(app.state, "mtproto_helper", None)
    if helper is not None:
        try:
            await helper.disconnect()
        except Exception:
            pass
        app.state.mtproto_helper = None
