"""F1: storage interface contract — FakeBackend implements what bot/mtproto must."""
from __future__ import annotations

import pytest

from tglink.storage import FakeBackend, ObjectRef


@pytest.mark.asyncio
async def test_store_open_roundtrip():
    b = FakeBackend()
    ref = await b.store(b"hello world", "h.txt")
    assert isinstance(ref, ObjectRef)
    assert ref.backend == "fake"
    assert await b.open(ref) == b"hello world"


@pytest.mark.asyncio
async def test_delete():
    b = FakeBackend()
    ref = await b.store(b"x", "x.bin")
    assert await b.delete(ref) is True
    assert await b.delete(ref) is False


@pytest.mark.asyncio
async def test_health():
    assert await FakeBackend().health() is True