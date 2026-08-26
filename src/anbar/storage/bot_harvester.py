"""Bot harvester: capture document file_id for messages posted to the channel.

In hybrid mode, files are uploaded via MTProto (fast, multi-part, no floodwait),
and the Bot in the channel reads the channel_post updates to capture the Bot API
`file_id` for each chunk. The file_id is stored in the object chunk manifest,
enabling fast CDN download via getFile with fallback to MTProto.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from ..db import Database

log = logging.getLogger("anbar.bot_harvester")
API_BASE = "https://api.telegram.org"


class BotHarvester:
    """Harvests Telegram Bot API file_ids from channel posts."""

    def __init__(self, bot_token: str, channel_id: str | int, db: Database | None = None) -> None:
        self.bot_token = bot_token
        self.channel_id = str(channel_id)
        self.db = db
        self._http = httpx.AsyncClient(
            base_url=f"{API_BASE}/bot{bot_token}",
            timeout=httpx.Timeout(20.0, connect=10.0),
        )
        self._msg_to_file_id: dict[int, str] = {}
        self._events: dict[int, asyncio.Event] = {}
        self._lock = asyncio.Lock()
        self._running = False
        self._task: asyncio.Task | None = None
        self._offset: int = 0
        if self.db:
            saved = self.db.kv_get("bot_harvester_offset")
            if saved and saved.isdigit():
                self._offset = int(saved)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(), name="bot_harvester_poll")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._http.aclose()

    def _extract_file_id(self, message: dict[str, Any]) -> tuple[int, str] | None:
        msg_id = message.get("message_id")
        if not msg_id:
            return None
        # Check document, video, audio, etc.
        for key in ("document", "video", "audio", "animation"):
            if key in message and "file_id" in message[key]:
                return int(msg_id), message[key]["file_id"]
        return None

    def _process_update(self, update: dict[str, Any]) -> None:
        update_id = update.get("update_id", 0)
        if update_id >= self._offset:
            self._offset = update_id + 1
            if self.db:
                self.db.kv_set("bot_harvester_offset", str(self._offset))

        msg = update.get("channel_post") or update.get("message")
        if not msg:
            return

        chat = msg.get("chat", {})
        chat_id_str = str(chat.get("id", ""))
        log.info("harvester update: msg_id=%s chat_id=%s", msg.get("message_id"), chat_id_str)
        # Process document uploads from any channel the bot is member of (or match configured)
        extracted = self._extract_file_id(msg)
        if extracted:
            mid, fid = extracted
            log.info("harvester captured: message_id=%d file_id=%s", mid, fid[:20])
            self._msg_to_file_id[mid] = fid
            if mid in self._events:
                self._events[mid].set()

    async def poll_once(self) -> int:
        """Fetch updates once and process them. Returns count of updates received."""
        try:
            r = await self._http.post(
                "/getUpdates",
                json={
                    "offset": self._offset,
                    "limit": 100,
                    "timeout": 0,
                },
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("ok"):
                    updates = data.get("result", [])
                    for u in updates:
                        self._process_update(u)
                    return len(updates)
        except Exception as e:
            log.debug("getUpdates error: %s", e)
        return 0

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                r = await self._http.post(
                    "/getUpdates",
                    json={
                        "offset": self._offset,
                        "limit": 100,
                        "timeout": 5,
                    },
                )
                if r.status_code == 200:
                    data = r.json()
                    if data.get("ok"):
                        updates = data.get("result", [])
                        for u in updates:
                            self._process_update(u)
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.debug("harvester poll error: %s", e)
                await asyncio.sleep(2.0)

    async def get_file_id_for_message(self, message_id: int, timeout: float = 3.0) -> str | None:
        """Wait up to `timeout` seconds for the bot to see `message_id`."""
        if message_id in self._msg_to_file_id:
            return self._msg_to_file_id[message_id]

        event = asyncio.Event()
        self._events[message_id] = event
        try:
            # Poll once immediately in case update is already waiting
            await self.poll_once()
            if message_id in self._msg_to_file_id:
                return self._msg_to_file_id[message_id]
            try:
                await asyncio.wait_for(event.wait(), timeout=timeout)
                return self._msg_to_file_id.get(message_id)
            except TimeoutError:
                return None
        finally:
            self._events.pop(message_id, None)
