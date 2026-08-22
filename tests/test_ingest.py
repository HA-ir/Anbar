"""URL ingest: job lifecycle, filename derivation, error paths."""
from __future__ import annotations

import asyncio

import pytest

from anbar.api.ingest import JOBS, _filename_from_url, _run_job, _UrlReader


def test_filename_from_url():
    assert _filename_from_url("https://x.com/a/b/file.zip?tok=1", None) == "file.zip"
    assert _filename_from_url("https://x.com/", None) == "ingest.bin"
    hdrs = {"content-disposition": 'attachment; filename="real name.bin"'}
    assert _filename_from_url("https://x.com/whatever", hdrs) == "real name.bin"


def test_url_reader_buffers_and_eof():
    class FakeResp:
        def __init__(self, pieces):
            self._p = pieces

        def aiter_bytes(self, n):
            async def gen():
                for p in self._p:
                    yield p
            return gen()

    async def run():
        r = _UrlReader(FakeResp([b"a" * 100, b"b" * 50]), idle_timeout_s=1)
        out = b""
        while True:
            piece = await r.read(64)
            if not piece:
                break
            out += piece
        return out

    data = asyncio.run(run())
    assert data == b"a" * 100 + b"b" * 50


def test_url_reader_idle_timeout():
    class FakeResp:
        def aiter_bytes(self, n):
            async def gen():
                yield b"x"
                await asyncio.sleep(3600)
            return gen()

    async def run():
        r = _UrlReader(FakeResp(), idle_timeout_s=0.15)
        await r.read(1024)

    with pytest.raises(RuntimeError, match="origin stalled"):
        asyncio.run(run())


def test_run_job_rejects_bad_status(client, monkeypatch):
    """Origin 404 → job state=error with message."""
    class FakeResp:
        status_code = 404
        headers = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, method, url):
            return FakeResp()

    monkeypatch.setattr("anbar.api.ingest.httpx.AsyncClient", FakeClient)
    app = client.app
    JOBS["t1"] = {"state": "pulling", "bytes": 0, "chunks": 0,
                  "started": 0.0, "key": None, "object": None, "error": None}
    asyncio.run(_run_job(app, "t1", "https://x/nope.bin", None))
    assert JOBS["t1"]["state"] == "error"
    assert "HTTP 404" in JOBS["t1"]["error"]
