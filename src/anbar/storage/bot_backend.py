"""Bot API storage backend.

Files are posted as documents into a private channel the bot administers.
The bot captures each document's `file_id` and later retrieves bytes via
`getFile` + the file CDN. Messages are NEVER deleted — deleting one destroys
the file (file_ids expire after re-download).
"""
from __future__ import annotations

import asyncio

import httpx

from .base import ObjectRef, StorageBackend

API_BASE = "https://api.telegram.org"


class TelegramError(Exception):
    def __init__(self, code: int, message: str, retry_after: int | None = None):
        self.code = code
        self.message = message
        self.retry_after = retry_after
        super().__init__(f"telegram error {code}: {message}")


class BotBackend(StorageBackend):
    name = "bot"
    # Telegram hard limit is 20 MB via the Bot API; stay under it.
    max_upload_bytes = 19 * 1024 * 1024

    def __init__(self, bot_token: str, channel_id: str) -> None:
        self._channel = channel_id
        self._http = httpx.AsyncClient(
            base_url=f"{API_BASE}/bot{bot_token}",
            timeout=httpx.Timeout(300.0, connect=15.0),
            limits=httpx.Limits(max_keepalive_connections=4, max_connections=8),
        )
        self._file_client = httpx.AsyncClient(
            base_url=f"{API_BASE}/file/bot{bot_token}",
            timeout=httpx.Timeout(600.0, connect=15.0),
        )

    # ── API plumbing ────────────────────────────────────────────────
    @staticmethod
    def _parse(body: dict) -> dict:
        """Extract `result` from a Telegram response or raise TelegramError."""
        if not body.get("ok"):
            e = body.get("error", {})
            retry_after = e.get("parameters", {}).get("retry_after")
            raise TelegramError(e.get("code", 500), e.get("description", "?"), retry_after)
        return body["result"]

    async def _call(self, method: str, **params) -> dict:
        r = await self._http.post(f"/{method}", data=params)
        return self._parse(r.json())

    async def _call_multipart(self, method: str, fields: dict, files: dict) -> dict:
        r = await self._http.post(f"/{method}", data=fields, files=files)
        return self._parse(r.json())

    def _is_rate_limited(self, e: TelegramError) -> bool:
        return e.code in (429, 402)

    # ── StorageBackend contract ─────────────────────────────────────
    async def store(self, data: bytes, name: str) -> ObjectRef:
        """Post one blob to the channel, return its file_id ref."""
        last: TelegramError | None = None
        for _attempt in range(5):
            try:
                result = await self._call_multipart(
                    "sendDocument",
                    fields={"chat_id": self._channel},
                    files={"document": (name, data, "application/octet-stream")},
                )
                fid = result["document"]["file_id"]
                return ObjectRef(
                    file_id=fid,
                    backend=self.name,
                    size=len(data),
                    name=name,
                    message_id=result.get("message_id"),
                )
            except TelegramError as e:
                last = e
                if self._is_rate_limited(e):
                    await asyncio.sleep((e.retry_after or 3) + 0.5)
                    continue
                break
        assert last is not None
        raise last

    async def open(self, ref: ObjectRef) -> bytes:
        """Fetch full blob bytes via getFile + CDN (bounded by chunk size)."""
        info = await self._call("getFile", file_id=ref.file_id)
        path = info["file_path"]
        r = await self._file_client.get(path)
        if r.status_code != 200:
            raise RuntimeError(f"file CDN returned {r.status_code} for {path}")
        return r.content

    async def delete(self, ref: ObjectRef) -> bool:
        """Delete the channel message holding this blob.

        WARNING: deleting also invalidates the file_id (Telegram expires
        file_ids once their message is gone). Only the admin path calls this.
        """
        if ref.message_id is None:
            return False
        try:
            await self._call("deleteMessage", chat_id=self._channel, message_id=ref.message_id)
            return True
        except TelegramError:
            return False

    async def health(self) -> bool:
        try:
            await self._call("getMe")
            return True
        except Exception:
            return False

    async def close(self) -> None:
        await self._http.aclose()
        await self._file_client.aclose()