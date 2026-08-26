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
    def add(self, obj_id: str, path: str, size: int) -> None:
        if size > self._max_bytes:  # object bigger than the whole budget
            return
        self._evict_for(size)
        self._entries.pop(obj_id, None)
        self._entries[obj_id] = (path, size, time.time())
        self._bytes += size

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
