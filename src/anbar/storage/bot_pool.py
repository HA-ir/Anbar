"""Multi-Bot Token Pool for distributed Bot CDN downloads.

When multiple bot tokens are configured, BotPool round-robins CDN download
requests across different bot tokens to distribute Telegram's per-bot rate
limits and eliminate CDN queuing stalls on massive multi-gigabyte transfers.

ARCH-01 (v0.15.23) extends the pool to uploads: `next()` hands out members
one-by-one so ObjectService can distribute stored chunks across tokens, and
`by_name()` lets the download/purge paths fetch a chunk from the exact member
that holds it (each chunk's manifest entry records the member name).
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
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
        # ARCH-01: stable per-member names ("bot", "bot:1", "bot:2", ...) are
        # recorded in chunk manifests, so they must be deterministic and never
        # shift with construction order elsewhere in the process.
        self._backends: list[BotBackend] = [
            BotBackend(
                token,
                self.channel_id,
                send_gap_s=send_gap_s,
                flood_budget_s=flood_budget_s,
                send_timeout_s=send_timeout_s,
                name="bot" if i == 0 else f"bot:{i}",
            )
            for i, token in enumerate(self.tokens)
        ]
        self._cycle = itertools.cycle(self._backends) if self._backends else None
        self._lock = asyncio.Lock()
        # ARCH-01: members currently serving a Telegram FloodWait penalty are
        # excluded from rotation until their TTL expires (kept in memory only).
        self._flood_until: dict[int, float] = {}  # index -> monotonic deadline
        self._flood_ttl_s = 60.0
        self._rr = 0  # round-robin counter for the flood-filtered path
        log.info("BotPool initialized with %d bot token(s)", len(self._backends))

    @property
    def primary(self) -> BotBackend | None:
        """Return the primary (first) bot backend in the pool."""
        return self._backends[0] if self._backends else None

    @property
    def size(self) -> int:
        return len(self._backends)

    def names(self) -> list[str]:
        """Stable member names, in pool order ("bot", "bot:1", ...)."""
        return [b.name for b in self._backends]

    def by_name(self, name: str | None) -> BotBackend | None:
        """Resolve a manifest backend name to its pool member.

        `None` and unknown names fall back to the primary member — chunks
        written before ARCH-01 (and single-token deployments) carry no name.
        """
        if not self._backends:
            return None
        if not name:
            return self._backends[0]
        for b in self._backends:
            if b.name == name:
                return b
        return self._backends[0]

    def contains(self, backend) -> bool:
        """True if `backend` is one of this pool's members (identity check).

        ObjectService distributes only when the pool actually owns the storage
        backend — hybrid deployments (mtproto primary + bot pool) must keep
        uploading through the primary.
        """
        return any(backend is b for b in self._backends)

    def mark_flood(self, name: str) -> None:
        """Take a member out of the upload rotation (FloodWait / budget blown)."""
        for i, b in enumerate(self._backends):
            if b.name == name:
                self._flood_until[i] = time.monotonic() + self._flood_ttl_s
                log.warning(
                    "pool member %s paused for %.0fs (flood)",
                    name,
                    self._flood_ttl_s,
                )
                return

    def next(self) -> BotBackend:
        """Next healthy member for a store (round-robin, flood-filtered).

        Falls back to the primary when every member is flood-paused.
        """
        if not self._backends:
            raise RuntimeError("BotPool has no active bot backends")
        if self._flood_until:
            now = time.monotonic()
            healthy = [
                b for i, b in enumerate(self._backends) if self._flood_until.get(i, 0) <= now
            ]
            if healthy:
                backend = healthy[self._rr % len(healthy)]
                self._rr += 1
                return backend
            return self._backends[0]
        # no flood tracking in play: preserve the exact round-robin iterator
        return next(self._cycle) if self._cycle else self._backends[0]

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

    async def send_text_event(self, text: str) -> dict | None:
        """Send a meta event text message to the storage channel."""
        if self._backends:
            return await self._backends[0].send_text_event(text)
        return None

    async def close(self) -> None:
        for b in self._backends:
            try:
                await b.close()
            except Exception as e:
                log.debug("error closing bot backend in pool: %s", e)
