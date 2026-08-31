"""ARCH-01: multi-token upload distribution over the BotPool.

Covers the design in IMPROVEMENT_PLAN.md §4:
- pool member naming (bot / bot:1 / bot:2) + by_name resolution
- manifest "k" key roundtrip (and "b" = bot_file_id is untouched)
- ObjectService distributes chunks across members (only when the pool owns
  the primary backend — hybrid must NOT distribute)
- FloodWait skips the throttled member and it returns after the TTL
- purge/rollback/delete route through the holding member
"""

from __future__ import annotations

import json
import time as time_mod
from types import SimpleNamespace

import pytest

from anbar.object_service import ObjectService
from anbar.objects import Chunk, Manifest
from anbar.storage import FakeBackend, FloodBudgetExceeded
from anbar.storage.bot_pool import BotPool

# ── fakes ────────────────────────────────────────────────────────────────────


class ByteReader:
    def __init__(self, data: bytes, piece: int = 8):
        self.data = data
        self.piece = piece
        self.i = 0

    async def read(self, n: int) -> bytes:
        if self.i >= len(self.data):
            return b""
        out = self.data[self.i : self.i + self.piece]
        self.i += self.piece
        return out


class FloodBackend(FakeBackend):
    """FakeBackend that raises FloodBudgetExceeded on demand."""

    def __init__(self):
        super().__init__()
        self.flood_next = False

    async def store(self, data, name, content_type=None, caption=None):
        if self.flood_next:
            self.flood_next = False
            raise FloodBudgetExceeded(429, "flood-limited: budget", retry_after=1)
        return await super().store(data, name, content_type=content_type, caption=caption)


class FakeDB:
    def __init__(self):
        self.kv: dict[str, str] = {}
        self.objects: list[dict] = []

    def kv_get(self, key, default=None):
        return self.kv.get(key, default)

    def kv_set(self, key, value):
        self.kv[key] = value

    def kv_delete(self, key):
        self.kv.pop(key, None)

    def insert_object(self, obj):
        self.objects.append(obj)

    def delete_object(self, obj_id):
        self.objects = [o for o in self.objects if o["id"] != obj_id]

    def kv_all(self):
        return list(self.kv.items())


class FakeSettings:
    chunk_size = 8
    hmac_secret = None


class FakePool:
    """Pool-shaped stand-in with FakeBackend members (no Telegram involved)."""

    def __init__(self, members):
        self._members = members
        self._flood: set[str] = set()
        self._rr = 0

    @property
    def primary(self):
        return self._members[0]

    @property
    def size(self):
        return len(self._members)

    def names(self):
        return [b.name for b in self._members]

    def by_name(self, name):
        if not name:
            return self._members[0]
        for b in self._members:
            if b.name == name:
                return b
        return self._members[0]

    def contains(self, backend):
        return any(backend is b for b in self._members)

    def mark_flood(self, name):
        self._flood.add(name)

    def next(self):
        healthy = [b for b in self._members if b.name not in self._flood]
        if not healthy:
            return self._members[0]
        b = healthy[self._rr % len(healthy)]
        self._rr += 1
        return b


def _fake_pool(n: int = 3):
    members = [FakeBackend() for _ in range(n)]
    # give each member the same stable names the real BotPool assigns
    for i, b in enumerate(members):
        b.name = "bot" if i == 0 else f"bot:{i}"
    return FakePool(members), members


def _svc(db, backend, pool=None, **kw) -> ObjectService:
    return ObjectService(
        backend=backend,
        db=db,
        settings=FakeSettings(),
        filename="f.bin",
        pool=pool,
        **kw,
    )


# ── 1. pool naming + by_name ────────────────────────────────────────────────


def test_pool_member_names_are_stable():
    pool = BotPool(["T0", "T1", "T2"], "-100123")
    assert pool.names() == ["bot", "bot:1", "bot:2"]
    assert pool.by_name("bot:2").bot_token == "T2"
    assert pool.by_name("bot").bot_token == "T0"
    # None / unknown → primary (compat with pre-ARCH-01 chunks)
    assert pool.by_name(None) is pool.primary
    assert pool.by_name("bot:99") is pool.primary
    assert pool.size == 3
    assert pool.contains(pool.by_name("bot:1"))
    assert not pool.contains(object())


# ── 2. manifest roundtrip with per-chunk backend ────────────────────────────


def test_manifest_roundtrip_with_backend_key():
    m = Manifest(
        chunks=[
            # new-style: named member + bot_file_id must coexist
            Chunk(index=0, size=4, file_id="f0", message_id=10,
                  bot_file_id="bf", backend="bot:1"),
            # old-style: no backend recorded
            Chunk(index=1, size=5, file_id="f1", message_id=11),
        ],
        total_size=9,
    )
    restored = Manifest.from_json(m.to_json())
    assert restored.chunks[0].backend == "bot:1"
    assert restored.chunks[0].bot_file_id == "bf"  # "b" key untouched
    assert restored.chunks[1].backend is None  # old chunks stay nameless
    # key "k" is literally in the JSON; "b" still means bot_file_id
    raw = json.loads(m.to_json())
    assert raw["chunks"][0]["k"] == "bot:1"
    assert raw["chunks"][0]["b"] == "bf"
    assert "k" not in raw["chunks"][1]


# ── 3. distribution across pool members ─────────────────────────────────────


@pytest.mark.asyncio
async def test_multi_backend_distribution():
    db = FakeDB()
    pool, members = _fake_pool(3)
    svc = _svc(db, members[0], pool)
    manifest, sha = await svc.store_stream(ByteReader(b"X" * 72))  # 9 chunks
    assert len(manifest.chunks) == 9
    # exactly 3 chunks per member, round-robin order
    per: dict[str, int] = {}
    for c in manifest.chunks:
        assert c.backend is not None and c.backend in pool.names()
        key: str = c.backend
        per[key] = per.get(key, 0) + 1
    assert per == {"bot": 3, "bot:1": 3, "bot:2": 3}
    stored_per = {b.name: len(b._store) for b in members}
    assert stored_per == {"bot": 3, "bot:1": 3, "bot:2": 3}
    # commit: row backend = chunk #0's holder; manifest keeps per-chunk truth
    obj_id = svc.commit(sha_hex=sha)
    row = db.objects[0]
    assert row["id"] == obj_id
    assert row["backend"] == "bot"  # chunk #0 lands on member #0
    assert Manifest.from_json(row["manifest"]).chunks[4].backend == "bot:1"


@pytest.mark.asyncio
async def test_single_member_pool_stays_legacy():
    """pool.size == 1 → exact old behaviour (no names in manifest)."""
    db = FakeDB()
    pool, members = _fake_pool(1)
    svc = _svc(db, members[0], pool)
    manifest, sha = await svc.store_stream(ByteReader(b"Y" * 24))
    assert all(c.backend is None for c in manifest.chunks)
    svc.commit(sha_hex=sha)
    assert db.objects[0]["backend"] == "bot"  # the single member's own name


@pytest.mark.asyncio
async def test_hybrid_pool_does_not_distribute():
    """Primary backend not in the pool (mtproto + bot CDN) → never rotate."""
    db = FakeDB()
    pool, members = _fake_pool(3)
    mtproto = FakeBackend()
    mtproto.name = "mtproto"
    svc = _svc(db, mtproto, pool)
    manifest, sha = await svc.store_stream(ByteReader(b"Z" * 48))
    assert all(c.backend is None for c in manifest.chunks)
    assert all(len(b._store) == 0 for b in members)  # nothing leaked to bots
    svc.commit(sha_hex=sha)
    assert db.objects[0]["backend"] == "mtproto"


# ── 4. FloodWait handling ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_floodwait_skips_backend():
    db = FakeDB()
    pool, members = _fake_pool(3)
    flaky = FloodBackend()
    flaky.name = "bot:1"
    flaky.flood_next = True  # raise exactly once, on its first chunk
    members[1] = flaky
    pool._members[1] = flaky
    svc = _svc(db, members[0], pool)
    manifest, _sha = await svc.store_stream(ByteReader(b"W" * 96))  # 12 chunks
    # 12 stores succeeded despite the flood (chunk retried on another member)
    total_stored = sum(len(b._store) for b in members)
    assert total_stored == 12
    assert len(manifest.chunks) == 12
    # the flood-paused member was marked and skipped afterwards
    assert "bot:1" in pool._flood
    assert all(c.backend != "bot:1" for c in manifest.chunks[1:])


def test_mark_flood_excludes_then_expires(monkeypatch):
    pool = BotPool(["T0", "T1"], "-100123")
    base = time_mod.monotonic()
    monkeypatch.setattr(time_mod, "monotonic", lambda: base)
    pool.mark_flood("bot:1")
    # while paused: every pick is the primary
    assert all(pool.next().name == "bot" for _ in range(5))
    # after the TTL the member becomes eligible again
    monkeypatch.setattr(time_mod, "monotonic", lambda: base + pool._flood_ttl_s + 1)
    picks = {pool.next().name for _ in range(4)}
    assert picks == {"bot", "bot:1"}


# ── 5. purge/rollback route to the holding member ───────────────────────────


@pytest.mark.asyncio
async def test_purge_deletes_from_right_backends():
    """Manifest rows with "k" are deleted via the matching pool member."""
    db = FakeDB()
    pool, members = _fake_pool(2)
    svc = _svc(db, members[0], pool)
    manifest, sha = await svc.store_stream(ByteReader(b"D" * 32))  # 4 chunks
    svc.commit(sha_hex=sha)
    row = dict(db.objects[0])

    from anbar.api.download import _purge_object_blobs

    deleted = await _purge_object_blobs(members[0], db, row, pool=pool)
    assert deleted == 4
    for b in members:
        assert len(b._store) == 0  # every member emptied


@pytest.mark.asyncio
async def test_rollback_uses_holding_member():
    db = FakeDB()
    pool, members = _fake_pool(2)
    svc = _svc(db, members[0], pool)
    await svc.store_stream(ByteReader(b"R" * 16))
    assert sum(len(b._store) for b in members) == 2
    deleted = await svc.rollback()
    assert deleted == 2
    assert sum(len(b._store) for b in members) == 0


@pytest.mark.asyncio
async def test_resume_keeps_chunk_backend_names():
    """A resumed upload carries "k" through the checkpoint envelope."""
    db = FakeDB()
    pool, members = _fake_pool(2)

    # phase 1: checkpoint 2 chunks, then "die" (simulate via a fresh service)
    svc1 = _svc(db, members[0], pool, upload_id="up1", resume_from=0)
    await svc1.store_stream(ByteReader(b"A" * 16))
    ck = json.loads(db.kv["upres:up1"])
    assert [c.get("k") for c in ck["chunks"]] == ["bot", "bot:1"]
    svc1.drop_checkpoint = lambda: None  # keep the checkpoint for phase 2

    # phase 2: resume — client resends the WHOLE file; the first 2 chunks are
    # duplicates that get drained, the rest are stored fresh.
    svc2 = _svc(db, members[0], pool, upload_id="up1", resume_from=2)
    manifest, sha = await svc2.store_stream(ByteReader(b"A" * 32))
    assert len(manifest.chunks) == 4
    # prior chunks keep their original member names
    assert manifest.chunks[0].backend == "bot"
    assert manifest.chunks[1].backend == "bot:1"
    # new chunks continue the round-robin
    assert manifest.chunks[2].backend == "bot"
    assert manifest.chunks[3].backend == "bot:1"
    svc2.commit(sha_hex=sha)
    restored = Manifest.from_json(db.objects[0]["manifest"])
    assert [c.backend for c in restored.chunks] == ["bot", "bot:1", "bot", "bot:1"]


# ── 6. download uses chunk backend (route-level) ────────────────────────────


def test_download_uses_chunk_backend(backend, client):
    """Full app flow: a manifest with "k" entries is served when the pool
    resolves the name back to the app's own backend."""
    r = client.post(
        "/api/v1/upload",
        files={"file": ("m.bin", b"payload-123", "application/octet-stream")},
        headers={"Authorization": "Bearer test-key"},
    )
    assert r.status_code == 200
    obj_id = r.json()["id"]

    # rewrite the manifest to point chunk 0 at a pool-resolvable name
    db = client.app.state.db
    row = db.get_object(obj_id)
    m = Manifest.from_json(row["manifest"])
    m.chunks[0].backend = "bot:7"
    db._conn.execute(
        "UPDATE objects SET manifest = ? WHERE id = ?",
        (m.to_json(), obj_id),
    )
    db._conn.commit()

    client.app.state.bot_pool = SimpleNamespace(
        by_name=lambda name: backend if name == "bot:7" else None
    )
    try:
        r = client.post(f"/f/{obj_id}/link", headers={"Authorization": "Bearer test-key"})
        assert r.status_code == 200
        url = r.json()["url"]
        r2 = client.get(url)
        assert r2.status_code == 200
        assert r2.content == b"payload-123"
    finally:
        client.app.state.bot_pool = None
