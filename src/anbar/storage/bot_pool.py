"""Multi-Bot Token Pool for distributed Bot CDN downloads.

When multiple bot tokens are configured, BotPool round-robins CDN download
requests across different bot tokens to distribute Telegram's per-bot rate
limits and eliminate CDN queuing stalls on massive multi-gigabyte transfers.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from collections.abc import Sequence

from .base import ObjectRef
from .bot_backend import BotBackend

log = logging.getLogger("anbar.bot_pool")


class BotPool:
    """Manages a pool of BotBackend instances for round-robin downloads."""

    def __init__(
        self,
        bot_tokens: Sequence[str],
        channel_id: str | int,
        send_gap_s: float = 1.1,
        flood_budget_s: float = 2400.0,
        send_timeout_s: float = 300.0,
    ) -> None:
        self.channel_id = str(channel_id)
        self.tokens = list(bot_tokens)
        self._backends: list[BotBackend] = [
            BotBackend(
                token,
                self.channel_id,
                send_gap_s=send_gap_s,
                flood_budget_s=flood_budget_s,
                send_timeout_s=send_timeout_s,
            )
            for token in self.tokens
        ]
        self._cycle = itertools.cycle(self._backends) if self._backends else None
        self._lock = asyncio.Lock()
        log.info("BotPool initialized with %d bot token(s)", len(self._backends))

    @property
    def primary(self) -> BotBackend | None:
        """Return the primary (first) bot backend in the pool."""
        return self._backends[0] if self._backends else None

    @property
    def size(self) -> int:
        return len(self._backends)

    async def open(self, ref: ObjectRef, max_retries: int = 3) -> bytes:
        """Download chunk using round-robin bot backend from the pool."""
        if not self._backends or self._cycle is None:
            raise RuntimeError("BotPool has no active bot backends")

        async with self._lock:
            backend = next(self._cycle)

        return await backend.open(ref, max_retries=max_retries)

    async def store(
        self,
        data: bytes,
        name: str,
        content_type: str | None = None,
        caption: str | None = None,
    ) -> ObjectRef:
        """Store chunk using round-robin bot backend from the pool."""
        if not self._backends or self._cycle is None:
            raise RuntimeError("BotPool has no active bot backends")

        async with self._lock:
            backend = next(self._cycle)

        return await backend.store(data, name, content_type=content_type, caption=caption)

    async def close(self) -> None:
        for b in self._backends:
            try:
                await b.close()
            except Exception as e:
                log.debug("error closing bot backend in pool: %s", e)
