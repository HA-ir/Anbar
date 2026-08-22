"""Resume: checkpoint kv bumps per chunk; resume drains stored chunks."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_resume_flow(client, monkeypatch):
    """First attempt stores 2 chunks then fails; second resumes from 2."""
    from anbar.api import upload as up

    app = client.app
    backend = app.state.backend
    db = app.state.db

    calls = {"n": 0}
    original_store = type(backend).store

    async def flaky_store(self, data, name, content_type=None):
        calls["n"] += 1
        if calls["n"] > 2:
            raise RuntimeError("boom")
        return await original_store(self, data, name)

    monkeypatch.setattr(type(backend), "store", flaky_store)

    class Rdr:
        """Yields 3 chunks of 8 bytes then ends."""

        def __init__(self):
            self.i = 0

        async def read(self, n):
            self.i += 1
            if self.i <= 3:
                return bytes([self.i]) * min(n, 8)
            return b""

    class FakeReq:
        def __init__(self, app):
            self.app = app

        def stream(self):
            # chunk_stream calls .read(n) on the returned object directly
            return Rdr()

    # chunker reads 8-byte pieces; settings.chunk_size is huge in tests,
    # so the reader's own read(n) drives piece boundaries — one chunk per
    # EOF. To get 3 chunks we monkeypatch the effective chunk size.
    monkeypatch.setattr(type(app.state.settings), "chunk_size",
                        property(lambda self: 8))

    req = FakeReq(app)
    with pytest.raises(Exception, match="storage error: boom"):
        await up._store_stream(req, req.stream(), "f.bin",
                               upload_id="u1", resume_from=0)
    import json as _json
    ck = _json.loads(db.kv_get("upres:u1") or "[]")
    assert len(ck) == 2  # two chunks checkpointed before the failure

    # resume from chunk 2: chunks 0-1 drained (duplicates), chunk 2 stored
    calls["n"] = 0
    req2 = FakeReq(app)
    manifest, sha = await up._store_stream(
        req2, req2.stream(), "f.bin", upload_id="u1", resume_from=2,
    )
    assert calls["n"] == 1          # only the third chunk hit the backend
    assert len(manifest.chunks) == 3
    # pre-seeded chunk metadata preserved from the checkpoint
    assert [c.size for c in manifest.chunks] == [8, 8, 8]
    # cleanup checkpoint key
    db.kv_del("upres:u1") if hasattr(db, "kv_del") else None
