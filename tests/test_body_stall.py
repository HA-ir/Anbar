"""Body-stall guard: client declares more Content-Length than it sends.

Regression test for the 500 MB bench bug — the bench wrote only 7×64 MiB
(448 MiB) but declared 500 MiB, so the server waited forever on body bytes
that never came. v0.8.4 aborts such uploads with 408 + rollback.
"""

from __future__ import annotations

import asyncio

import pytest


def test_stalled_body_aborts_with_408(client):
    """A client that lies about Content-Length gets a 408, not a hang."""
    from anbar.api.upload import BodyReadTimeout, _RequestBodyReader

    class FakeIter:
        """Yields one chunk then blocks forever."""

        def __init__(self):
            self._sent = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._sent:
                self._sent = True
                return b"z" * 4096
            await asyncio.sleep(3600)  # stall

    class FakeRequest:
        def stream(self):
            return FakeIter()

    reader = _RequestBodyReader(FakeRequest(), idle_timeout_s=0.2)
    with pytest.raises(BodyReadTimeout):
        asyncio.run(reader.read(16 * 1024 * 1024))


def test_body_reader_buffers_across_stream_chunks():
    """read(n) returns exactly n bytes even when the stream yields smaller pieces."""
    import asyncio

    from anbar.api.upload import _RequestBodyReader

    pieces = [b"a" * 100, b"b" * 50, b"c" * 30]

    class FakeIter:
        def __init__(self):
            self.i = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.i >= len(pieces):
                raise StopAsyncIteration
            v = pieces[self.i]
            self.i += 1
            return v

    class FakeRequest:
        def stream(self):
            return FakeIter()

    async def run():
        r = _RequestBodyReader(FakeRequest(), idle_timeout_s=1.0)
        out = bytearray()
        while True:
            piece = await r.read(64)
            if not piece:
                break
            out.extend(piece)
        return bytes(out)

    data = asyncio.run(run())
    assert data == b"a" * 100 + b"b" * 50 + b"c" * 30
