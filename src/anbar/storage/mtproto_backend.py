"""MTProto storage backend (F5).

A dedicated Telegram *user* account stores blobs in its Saved Messages.
User accounts may send files up to 2 GB — far beyond the Bot API's 20 MB.

The session file is created by a one-time interactive `anbarctl login`
(phone + code, optional 2FA) and reused on every server start: the server
itself never authenticates, it just loads the existing session.
"""
from __future__ import annotations

import io
from pathlib import Path

from .base import ObjectRef, StorageBackend

# Telegram user-account send limit.
_MAX_SEND_BYTES = 2 * 1024 * 1024 * 1024


class MTProtoBackend(StorageBackend):
    name = "mtproto"
    max_upload_bytes = _MAX_SEND_BYTES

    def __init__(self, api_id: int, api_hash: str, session_file: str,
                 client=None, peer: str = "me") -> None:
        if client is None:
            from telethon import TelegramClient  # lazy: optional at import time

            client = TelegramClient(str(session_file), api_id, api_hash)
        self._client = client
        self._session_file = str(session_file)
        self._peer = peer  # destination entity: "me" (Saved) or a channel id
        self._connected = False

    async def connect(self) -> None:
        """Load the session and connect. Fails if `anbarctl login` was never run."""
        if self._connected:
            return
        if not self._session_file or not Path(self._session_file).exists():
            raise RuntimeError(
                "mtproto: session file not found "
                f"({self._session_file}). Run `anbarctl login` once (see "
                "docs/DEPLOY.md, 'MTProto backend') and point "
                "ANBAR_SESSION_FILE at the resulting file."
            )
        try:
            await self._client.start()
        except EOFError as e:
            raise RuntimeError(
                "mtproto: Telethon asked for interactive input (phone/code) — "
                "the session file is missing or not logged in. Run "
                "`anbarctl login` once (needs a TTY: docker exec -it)."
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"mtproto: could not start client ({e}). If the account was "
                "logged out or the session is stale, re-run `anbarctl login`."
            ) from e
        self._connected = True

    # ── StorageBackend contract ─────────────────────────────────────
    async def store(self, data: bytes, name: str,
                    content_type: str | None = None) -> ObjectRef:
        """Upload one blob as a document into the destination peer.

        `content_type` is accepted for the StorageBackend contract but
        deliberately ignored: everything is sent as a force_document so the
        blob stays a byte-exact opaque file in the channel.
        """
        msg = await self._client.send_file(self._peer, data, file_name=name,
                                           force_document=True)
        doc = msg.media.document if msg.media else None
        if doc is None:
            raise RuntimeError(f"mtproto: message {msg.id} has no document")
        return ObjectRef(
            file_id=str(doc.id),
            backend=self.name,
            size=len(data),
            name=name,
            message_id=msg.id,
        )

    async def open(self, ref: ObjectRef) -> bytes:
        """Re-fetch a blob from Saved Messages (bounded by chunk size)."""
        if ref.message_id is None:
            raise RuntimeError("mtproto ref without message_id")
        msg = await self._client.get_message(self._peer, ref.message_id)
        if msg is None or msg.media is None:
            raise FileNotFoundError(
                f"mtproto: message {ref.message_id} not found or has no document")
        buf = io.BytesIO()
        await self._client.download_media(msg, file=buf)
        return buf.getvalue()

    async def delete(self, ref: ObjectRef) -> bool:
        """Delete the Saved Message holding this blob."""
        if ref.message_id is None:
            return False
        try:
            await self._client.delete_messages(self._peer, ref.message_id)
            return True
        except Exception:  # noqa: BLE001 - best-effort remote cleanup
            return False

    async def health(self) -> bool:
        try:
            return bool(await self._client.is_user_authorized())
        except Exception:
            return False

    async def close(self) -> None:
        try:
            await self._client.disconnect()
        finally:
            self._connected = False