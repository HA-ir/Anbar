"""MTProto storage backend (F5).

A dedicated Telegram *user* account stores blobs in its Saved Messages.
User accounts may send files up to 2 GB — far beyond the Bot API's 20 MB.

The session file is created by a one-time interactive `anbarctl login`
(phone + code, optional 2FA) and reused on every server start: the server
itself never authenticates, it just loads the existing session.
"""

from __future__ import annotations

import asyncio
import io
import os
from pathlib import Path

from .base import ObjectRef, StorageBackend

# Telegram user-account send limit.
_MAX_SEND_BYTES = 2 * 1024 * 1024 * 1024

# Parallel SaveBigFilePart requests during upload (RTT-bound otherwise).
_UPLOAD_PART_BYTES = 524288  # 512 KB — Telegram's big-file part ceiling
_UPLOAD_WORKERS = 8

# Parallel ranged iter_download workers during open() (single-connection
# iter_download tops out ~3.4 MB/s; 6 workers reach ~2x on DC4).
_DOWNLOAD_WORKERS = 6
_DOWNLOAD_RANGE = 32 * 1024 * 1024  # per-worker slice granularity (32 MB)


class MTProtoBackend(StorageBackend):
    name = "mtproto"
    max_upload_bytes = _MAX_SEND_BYTES

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_file: str,
        client=None,
        peer: str | int = "me",
        export_conns: int = 0,
    ) -> None:
        if client is None:
            from telethon import TelegramClient  # lazy: optional at import time

            client = TelegramClient(str(session_file), api_id, api_hash)
        self._client = client
        self._session_file = str(session_file)
        self._api_id = api_id
        self._api_hash = api_hash
        self._peer_spec: str | int = peer  # "me" (Saved) or a channel id
        self._peer = peer  # resolved entity after connect()
        self._connected = False
        # FastTelethon-style extra download connections (exported auth).
        self.export_conns = export_conns  # admin-tunable at runtime; 0 = off
        self._pool: list = []  # connected TelegramClient instances
        self._pool_lock = asyncio.Lock()

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
        # Resolve the destination peer once, up front. Telethon's string
        # parsing of marked channel ids ("-100…") requires a cache hit and
        # fails on fresh sessions, while the integer form resolves reliably.
        if self._peer_spec != "me":
            try:
                self._peer = await self._client.get_entity(int(self._peer_spec))
            except ValueError as e:
                raise RuntimeError(
                    f"mtproto: cannot resolve peer {self._peer_spec!r} — the "
                    "account may not be a member of that channel."
                ) from e
        self._connected = True

    # ── StorageBackend contract ─────────────────────────────────────
    async def store(self, data: bytes, name: str, content_type: str | None = None) -> ObjectRef:
        """Upload one blob as a document into the destination peer.

        `content_type` is accepted for the StorageBackend contract but
        deliberately ignored: everything is sent as a force_document so the
        blob stays a byte-exact opaque file in the channel.

        Uploaded with parallel SaveBigFilePart requests (512 KB parts,
        _UPLOAD_WORKERS in flight): a single Telethon connection is
        RTT-bound at ~3 MB/s sequentially; modest pipelining reaches
        ~5 MB/s without tripping flood limits.
        """
        handle = await self._run_healed(self._upload_parallel, data, name)
        msg = await self._run_healed(
            self._client.send_file,
            self._peer,
            handle,
            file_name=name,
            force_document=True,
        )
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

    async def _upload_parallel(self, data: bytes, name: str):
        """Upload bytes as a big file with pipelined 512 KB part requests.

        Returns the InputFile handle for send_file(). A fresh file_id per
        upload; md5 is not needed for InputFileBig.
        """
        from telethon.tl.functions.upload import SaveBigFilePartRequest
        from telethon.tl.types import InputFileBig

        file_id = int.from_bytes(os.urandom(8), "big", signed=True)
        parts = max(1, (len(data) + _UPLOAD_PART_BYTES - 1) // _UPLOAD_PART_BYTES)
        sem = asyncio.Semaphore(_UPLOAD_WORKERS)

        async def put(index: int) -> None:
            async with sem:
                await self._client(
                    SaveBigFilePartRequest(
                        file_id=file_id,
                        file_part=index,
                        bytes=data[index * _UPLOAD_PART_BYTES : (index + 1) * _UPLOAD_PART_BYTES],
                        file_total_parts=parts,
                    )
                )

        await asyncio.gather(*[put(i) for i in range(parts)])
        return InputFileBig(id=file_id, parts=parts, name=name)

    async def open(self, ref: ObjectRef) -> bytes:
        """Re-fetch a blob from the destination peer (bounded by chunk size)."""
        if ref.message_id is None:
            raise RuntimeError("mtproto ref without message_id")

        async def _fetch():
            msg = await self._client.get_messages(self._peer, ids=ref.message_id)
            if msg is None or msg.media is None:
                raise FileNotFoundError(
                    f"mtproto: message {ref.message_id} not found or has no document"
                )
            buf = io.BytesIO()
            async for piece in self._client.iter_download(msg, request_size=524288):
                buf.write(piece)
            return buf.getvalue()

        return await self._run_healed(_fetch)

    async def delete(self, ref: ObjectRef) -> bool:
        """Delete the Saved Message holding this blob."""
        if ref.message_id is None:
            return False
        try:
            await self._client.delete_messages(self._peer, ref.message_id)
            return True
        except Exception:  # noqa: BLE001 - best-effort remote cleanup
            return False

    async def _reconnect(self) -> None:
        """Recover a dead Telethon connection (server drop, session kicked,
        keepalive crash). Telethon's own reconnect only covers transport
        errors; after 'Cannot send requests while disconnected' the client
        object is unusable until disconnect()+start() run again."""
        try:
            await self._client.disconnect()
        except Exception:
            pass
        self._connected = False
        await self.connect()

    def _is_dead_link(self, e: Exception) -> bool:
        text = str(e).lower()
        markers = (
            "cannot send requests while disconnected",
            "connection reset by peer",
            "connection closed",
            "not connected",
            "brokenpipe",
            "database or disk is full",  # telegram session-misuse surfacing
        )
        return any(m in text for m in markers)

    async def _run_healed(self, op, *args, retries: int = 2, **kwargs):
        """Run one storage RPC; on a dead link reconnect and retry.

        FloodWait and other Telegram-side refusals propagate unchanged —
        only broken-transport states are healed here.
        """
        last: Exception | None = None
        for attempt in range(retries + 1):
            try:
                if not self._connected:
                    await self.connect()
                return await op(*args, **kwargs)
            except Exception as e:  # noqa: BLE001 - inspect then re-raise
                if attempt < retries and self._is_dead_link(e):
                    last = e
                    await self._reconnect()
                    continue
                raise
        raise last  # pragma: no cover - loop always returns or raises

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
        await self._close_pool()

    # ── FastTelethon-style exported-auth download pool ──────────────
    async def _close_pool(self) -> None:
        """Disconnect and drop every pooled export client."""
        async with self._pool_lock:
            old, self._pool = self._pool, []
        for c in old:
            try:
                await c.disconnect()
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass

    async def set_export_conns(self, n: int) -> None:
        """Admin toggle: 0 disables extra connections, N>0 keeps a pool of
        N exported-auth clients warm for parallel ranged downloads."""
        n = max(0, min(8, int(n)))
        self.export_conns = n
        if n == 0:
            await self._close_pool()
