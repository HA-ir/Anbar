"""Bot API storage backend.

Files are posted as documents into a private channel the bot administers.
The bot captures each document's `file_id` and later retrieves bytes via
`getFile` + the file CDN. Messages are NEVER deleted — deleting one destroys
the file (file_ids expire after re-download).

Flood management (v0.8.3): Telegram throttles *upload* bursts per account
(429 FloodWait, `retry_after` ~30s once ~20 rapid 16 MB posts pile up).
Two mechanisms keep large files (64+ chunks) working:

- a **pacing gap** between consecutive sends (`send_gap_s`, ~1.1 s) keeps
  the upload rate inside the burst window, so short/medium files stay fast
  and 1 GB only pays for the excess;
- **unbounded FloodWait retry** inside a per-call budget
  (`flood_budget_s`, ~40 min): a stalled chunk waits out the 429 window
  instead of giving up after a fixed 5 attempts.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from .base import ObjectRef, StorageBackend

API_BASE = "https://api.telegram.org"

log = logging.getLogger("anbar.bot_backend")


class TelegramError(Exception):
    def __init__(
        self,
        code: int,
        message: str,
        retry_after: int | None = None,
        http_status: int = 400,
    ):
        self.code = code
        self.message = message
        self.retry_after = retry_after
        self.http_status = http_status  # 5xx for transport errors, else the
        # telegram-level code (429 = flood-waitable)
        super().__init__(f"telegram error {code}: {message}")


class FloodBudgetExceeded(TelegramError):
    """Rate-limit retries exhausted the per-call budget — the client should
    retry the whole request later (surfaced as HTTP 504, not 502)."""


class BotBackend(StorageBackend):
    name = "bot"
    # Telegram hard limit is 20 MB via the Bot API; stay under it.
    max_upload_bytes = 19 * 1024 * 1024

    # flood management knobs (v0.8.3)
    send_gap_s = 1.1  # inter-send pacing; keeps bursts inside the 429 window
    flood_budget_s = 2400.0  # max seconds one send() waits out 429s (~40 min)

    def __init__(
        self,
        bot_token: str,
        channel_id: str,
        send_gap_s: float | None = None,
        flood_budget_s: float | None = None,
    ) -> None:
        self._channel = channel_id
        self.send_gap_s = send_gap_s if send_gap_s is not None else self.send_gap_s
        self.flood_budget_s = (
            flood_budget_s if flood_budget_s is not None else self.flood_budget_s
        )
        self._http = httpx.AsyncClient(
            base_url=f"{API_BASE}/bot{bot_token}",
            timeout=httpx.Timeout(300.0, connect=15.0),
            limits=httpx.Limits(max_keepalive_connections=4, max_connections=8),
        )
        self._file_client = httpx.AsyncClient(
            base_url=f"{API_BASE}/file/bot{bot_token}",
            timeout=httpx.Timeout(600.0, connect=15.0),
        )
        self._send_lock = asyncio.Lock()  # serialises sendDocument calls
        self._last_send_at = 0.0

    # ── API plumbing ────────────────────────────────────────────────
    @staticmethod
    def _parse(body: dict) -> dict:
        """Extract `result` from a Telegram response or raise TelegramError."""
        if not body.get("ok"):
            e = body.get("error", {})
            retry_after = e.get("parameters", {}).get("retry_after")
            code = e.get("code", 500)
            desc = e.get("description") or "(no description)"
            raise TelegramError(code, desc, retry_after, http_status=code)
        return body["result"]

    async def _call(self, method: str, **params) -> dict:
        try:
            r = await self._http.post(f"/{method}", data=params)
        except httpx.HTTPError as e:
            raise TelegramError(502, f"telegram transport: {e.__class__.__name__}",
                                http_status=502) from e
        return self._parse(r.json())

    async def _call_multipart(self, method: str, fields: dict, files: dict) -> dict:
        try:
            r = await self._http.post(f"/{method}", data=fields, files=files)
        except httpx.HTTPError as e:
            raise TelegramError(502, f"telegram transport: {e.__class__.__name__}",
                                http_status=502) from e
        return self._parse(r.json())

    def _is_rate_limited(self, e: TelegramError) -> bool:
        # 429/402 = account flood window (wait retry_after); 500/502 =
        # Telegram's own transient server errors (often description-less) —
        # a short retry also covers these; everything else is fatal.
        return e.code in (429, 402, 500, 502)

    # ── StorageBackend contract ─────────────────────────────────────
    async def store(self, data: bytes, name: str) -> ObjectRef:
        """Post one blob to the channel, return its file_id ref.

        Paced by a single send queue and retried through FloodWait up to
        `flood_budget_s`; see module docstring for why.
        """
        deadline = asyncio.get_running_loop().time() + self.flood_budget_s
        while True:
            try:
                result = await self._paced_multipart("sendDocument", name, data)
            except TelegramError as e:
                if self._is_rate_limited(e):
                    wait_s = (e.retry_after or 3) + 0.5
                    if asyncio.get_running_loop().time() + wait_s > deadline:
                        raise FloodBudgetExceeded(
                            429,
                            f"flood-limited: waited > {self.flood_budget_s:.0f}s "
                            f"waiting out a 429 (last: retry_after "
                            f"{e.retry_after}s) — try again later",
                            retry_after=e.retry_after,
                            http_status=504,
                        ) from e
                    log.info("flood wait %ss before retrying %s", int(wait_s), name)
                    await asyncio.sleep(wait_s)
                    continue
                raise
            fid = result["document"]["file_id"]
            return ObjectRef(
                file_id=fid,
                backend=self.name,
                size=len(data),
                name=name,
                message_id=result.get("message_id"),
            )

    async def _paced_multipart(self, method: str, name: str, data: bytes) -> dict:
        """One sendDocument through the pacing queue (gap between sends)."""
        async with self._send_lock:
            now = asyncio.get_running_loop().time()
            gap = self._last_send_at + self.send_gap_s - now
            if gap > 0:
                await asyncio.sleep(gap)
            try:
                return await self._call_multipart(
                    method,
                    fields={"chat_id": self._channel},
                    files={"document": (name, data, "application/octet-stream")},
                )
            finally:
                self._last_send_at = asyncio.get_running_loop().time()

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