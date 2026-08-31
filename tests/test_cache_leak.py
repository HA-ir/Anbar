"""Loop #6 audit tests (B-051, B-052, B-053)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from anbar.cache import DiskLRU


@pytest.fixture()
def lru(tmp_path: Path) -> DiskLRU:
    return DiskLRU(tmp_path / "cache", max_bytes=1000)


def _fill(lru: DiskLRU, obj_id: str, size: int) -> str:
    p = lru.new_entry_path()
    with open(p, "wb") as f:
        f.write(b"x" * size)
    return p


def test_add_replace_unlinks_old_temp(tmp_path: Path, lru: DiskLRU):
    """B-051: re-adding the same id must unlink the replaced temp file."""
    p1 = _fill(lru, "obj1", 100)
    assert lru.add("obj1", p1, 100) is True
    assert os.path.exists(p1)

    p2 = _fill(lru, "obj1", 100)
    assert lru.add("obj1", p2, 100) is True
    # the replaced entry's temp file must be gone, not orphaned on disk
    assert not os.path.exists(p1)
    assert os.path.exists(p2)
    assert lru.size() == 100  # accounting stays exact, no double-count
    assert lru.count() == 1


def test_add_reject_unlinks_caller_tmp(tmp_path: Path, lru: DiskLRU):
    """B-051: rejected (over-budget) adds must not leak the caller's tmp."""
    orphan = _fill(lru, "big", 2000)
    assert lru.add("big", orphan, 2000) is False
    assert not os.path.exists(orphan)
    assert lru.count() == 0
    assert lru.size() == 0


def test_evict_unlinks(tmp_path: Path, lru: DiskLRU):
    """Sanity: LRU eviction still unlinks evicted temps."""
    for i in range(4):
        p = _fill(lru, f"o{i}", 400)
        assert lru.add(f"o{i}", p, 400) is True
    # budget 1000: each over-budget add evicts oldest → only 2 fit (800)
    assert lru.count() == 2
    assert lru.size() == 800
    # the two evicted temps must actually be gone from disk
    assert not os.path.exists(lru.get("o0") or "x")
    assert lru.get("o0") is None
    assert lru.get("o1") is None
