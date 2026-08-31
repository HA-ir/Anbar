"""Ephemeral LRU file cache for full objects (F6).

Optional and OFF by default. Cached entries are plain temp files under
`data/cache` (an ephemeral volume): the zero-retention promise is about
*permanent* storage — these files are evicted when the budget fills or the
container restarts. Advisory only: a miss just refetches from the backend.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from collections import OrderedDict
from pathlib import Path

_READ = 1024 * 1024  # 1 MB per read; keeps event-loop blocking minimal


def _mk_tmp(cache_dir: Path) -> str:
    fd, p = tempfile.mkstemp(prefix="anbar-", dir=str(cache_dir))
    os.close(fd)
    return p


class DiskLRU:
    """LRU cache of whole objects as temp files, bounded by `max_bytes`.

    Oldest-access-first eviction removes files. An entry larger than the
    whole budget is never cached.
    """

    def __init__(self, cache_dir: Path, max_bytes: int) -> None:
        self._dir = Path(cache_dir)
        self._max_bytes = max_bytes
        self._entries: OrderedDict[str, tuple[str, int, float]] = OrderedDict()
        self._bytes = 0
        self._dir.mkdir(parents=True, exist_ok=True)

    def new_entry_path(self) -> str:
        """Create an empty temp file the caller fills before `add()`."""
        return _mk_tmp(self._dir)

    # -- queries -----------------------------------------------------------
    def contains(self, obj_id: str) -> bool:
        return obj_id in self._entries

    def get(self, obj_id: str) -> str | None:
        """Touch the entry (LRU) and return its file path, or None on miss."""
        e = self._entries.get(obj_id)
        if e is None:
            return None
        path, size, _at = e
        if not Path(path).exists():  # pruned externally — drop the entry
            self.remove(obj_id)
            return None
        self._entries.pop(obj_id)
        self._entries[obj_id] = (path, size, time.time())
        return path

    def size(self) -> int:
        return self._bytes

    def count(self) -> int:
        return len(self._entries)

    # -- mutations ----------------------------------------------------------
    def add(self, obj_id: str, path: str, size: int) -> bool:
        """Commit a filled temp file as the cache entry for `obj_id`.

        Returns True when committed, False when rejected (object larger
        than the whole budget). In both the reject path and the
        same-id-replace path the caller's temp file is unlinked here so
        no orphan temp file leaks onto disk (B-051).
        """
        if size > self._max_bytes:  # object bigger than the whole budget
            try:
                os.unlink(path)
            except OSError:
                pass
            return False
        self._evict_for(size)
        old = self._entries.pop(obj_id, None)
        if old is not None:  # replaced entry: unlink its temp file too
            try:
                os.unlink(old[0])
            except OSError:
                pass
            self._bytes -= old[1]
        self._entries[obj_id] = (path, size, time.time())
        self._bytes += size
        return True

    def remove(self, obj_id: str) -> None:
        e = self._entries.pop(obj_id, None)
        if e is None:
            return
        self._bytes -= e[1]
        try:
            os.unlink(e[0])
        except OSError:
            pass

    def remove_prefix(self, prefix: str) -> None:
        """Drop every entry whose id starts with `prefix` (object delete)."""
        for key in [k for k in self._entries if k.startswith(prefix)]:
            self.remove(key)

    def close(self) -> None:
        for _obj_id, (path, _size, _at) in list(self._entries.items()):
            try:
                os.unlink(path)
            except OSError:
                pass
        self._entries.clear()
        self._bytes = 0

    def _evict_for(self, need: int) -> None:
        while self._entries and self._bytes + need > self._max_bytes:
            _old_id, (path, size, _at) = self._entries.popitem(last=False)
            self._bytes -= size
            try:
                os.unlink(path)
            except OSError:
                pass


# ── file helpers (sync reads run off the event loop) ──────────────────────
async def iter_range(path: str, start: int, n: int):
    """Yield `n` bytes from `path` starting at `start` (async, chunked)."""

    def _read(pos: int, want: int) -> bytes:
        with open(path, "rb") as f:
            f.seek(pos)
            return f.read(want)

    pos = start
    while n > 0:
        take = min(_READ, n)
        yield await asyncio.to_thread(_read, pos, take)
        pos += take
        n -= take


# ── PERF-01: per-chunk micro cache (seek accelerator) ─────────────────────


class ChunkMicroCache:
    """Tiny in-RAM LRU of the most recently fetched chunks (PERF-01).

    Media players seek constantly; without this every seek into an already-
    visited chunk re-downloads the whole 16MB blob from Telegram. This cache
    holds the last few chunks as raw bytes so repeated seeks within a
    playback window are served from memory.

    Deliberately separate from :class:`DiskLRU` (the whole-object cache):
    - keyed by (object_id, chunk_index), holding ONE chunk (~16MB max)
    - short TTL (default 120s) — pure seek accelerator, not a retention layer
    - RAM-only, bounded by a small budget (default 32MB ≈ 2 chunks)
    - a chunk bigger than the whole budget is never admitted
    - zero disk writes: the zero-retention promise is untouched
    """

    def __init__(self, max_bytes: int, ttl_s: float = 120.0) -> None:
        self._max_bytes = max(0, max_bytes)
        self._ttl_s = ttl_s
        self._entries: OrderedDict[tuple[str, int], tuple[bytes, float]] = OrderedDict()
        self._bytes = 0
        # stats (cumulative, for /admin/status observability)
        self.hits = 0
        self.misses = 0

    def enabled(self) -> bool:
        return self._max_bytes > 0

    def get(self, obj_id: int | str, index: int) -> bytes | None:
        """Return the cached chunk bytes, or None on miss/expiry."""
        key = (obj_id, index)
        e = self._entries.get(key)
        if e is None:
            self.misses += 1
            return None
        data, at = e
        if (time.time() - at) > self._ttl_s:  # expired — treat as a miss
            self._entries.pop(key, None)
            self._bytes -= len(data)
            self.misses += 1
            return None
        self._entries.move_to_end(key)  # LRU touch
        self.hits += 1
        return data

    def put(self, obj_id: int | str, index: int, data: bytes) -> None:
        """Admit a fetched chunk. Oversized chunks are silently dropped."""
        if not self.enabled() or len(data) > self._max_bytes:
            return
        key = (obj_id, index)
        old = self._entries.pop(key, None)
        if old is not None:
            self._bytes -= len(old[0])
        self._evict_for(len(data))
        self._entries[key] = (data, time.time())
        self._bytes += len(data)

    def remove_object(self, obj_id: str) -> None:
        """Drop every chunk of one object (delete/purge path)."""
        for key in [k for k in self._entries if k[0] == obj_id]:
            data, _at = self._entries.pop(key)
            self._bytes -= len(data)

    def size(self) -> int:
        return self._bytes

    def count(self) -> int:
        return len(self._entries)

    def close(self) -> None:
        self._entries.clear()
        self._bytes = 0

    def _evict_for(self, need: int) -> None:
        while self._entries and self._bytes + need > self._max_bytes:
            _key, (data, _at) = self._entries.popitem(last=False)
            self._bytes -= len(data)
