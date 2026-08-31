"""PERF-01: chunk micro-cache — repeated seeks must not re-hit the backend.

The disk LRU (F6) only serves FULL downloads; range requests (media seeking)
always walked the backend path, re-downloading the whole 16MB chunk for a
few seconds of playback. The micro cache holds recently fetched chunks in
RAM (bounded, TTL'd, zero disk writes) so a second seek into the same chunk
is served from memory.
"""

from __future__ import annotations

import time

import pytest

from anbar.cache import ChunkMicroCache

CHUNK = 16 * 1024 * 1024
# 2 chunks: 16MB + 3MB (mirrors test_download.py's multi-chunk payload shape)
PAYLOAD = bytes(range(256)) * (CHUNK // 256) + bytes(range(256)) * (3 * 1024 * 1024 // 256)

AUTH = {"Authorization": "Bearer test-key"}


@pytest.fixture()
def small_payload_app(client, backend):
    """Standard client fixture; uploads the two-chunk payload once."""
    r = client.post(
        "/api/v1/upload",
        files={"file": ("seek.bin", PAYLOAD, "application/octet-stream")},
        headers=AUTH,
    )
    assert r.status_code == 200, r.text
    obj = r.json()["id"]
    r = client.post(f"/f/{obj}/link", headers=AUTH)
    assert r.status_code == 200, r.text
    return obj, r.json()["url"]


def _get_range(client, url, start, end):
    return client.get(url, headers={"Range": f"bytes={start}-{end}"})


class TestChunkMicroCacheUnit:
    """Direct unit tests for the cache itself."""

    def test_put_get_roundtrip(self):
        cc = ChunkMicroCache(1024)
        cc.put("obj1", 0, b"hello")
        assert cc.get("obj1", 0) == b"hello"
        assert (cc.hits, cc.misses) == (1, 0)

    def test_miss_counts(self):
        cc = ChunkMicroCache(1024)
        assert cc.get("nope", 3) is None
        assert (cc.hits, cc.misses) == (0, 1)

    def test_disabled_zero_budget(self):
        cc = ChunkMicroCache(0)
        assert not cc.enabled()
        cc.put("obj1", 0, b"data")
        assert cc.get("obj1", 0) is None
        assert cc.count() == 0

    def test_oversized_chunk_never_admitted(self):
        cc = ChunkMicroCache(4)
        cc.put("obj1", 0, b"toobig")  # 6 bytes > 4-byte budget
        assert cc.get("obj1", 0) is None
        assert cc.count() == 0

    def test_lru_eviction(self):
        cc = ChunkMicroCache(10)  # fits two 4-byte entries
        cc.put("o", 0, b"aaaa")
        cc.put("o", 1, b"bbbb")
        assert cc.count() == 2
        cc.put("o", 2, b"cccc")  # evicts chunk 0 (oldest)
        assert cc.get("o", 0) is None
        assert cc.get("o", 1) == b"bbbb"
        assert cc.get("o", 2) == b"cccc"

    def test_lru_touch_resists_eviction(self):
        cc = ChunkMicroCache(10)
        cc.put("o", 0, b"aaaa")
        cc.put("o", 1, b"bbbb")
        assert cc.get("o", 0) == b"aaaa"  # touch chunk 0 → now newest
        cc.put("o", 2, b"cccc")  # evicts chunk 1 instead
        assert cc.get("o", 0) == b"aaaa"
        assert cc.get("o", 1) is None

    def test_ttl_expiry(self):
        cc = ChunkMicroCache(1024, ttl_s=0.05)
        cc.put("o", 0, b"data")
        assert cc.get("o", 0) == b"data"
        time.sleep(0.08)
        assert cc.get("o", 0) is None  # expired → miss, entry dropped
        assert cc.count() == 0

    def test_replace_same_key(self):
        cc = ChunkMicroCache(1024)
        cc.put("o", 0, b"old")
        cc.put("o", 0, b"new")
        assert cc.get("o", 0) == b"new"
        assert cc.count() == 1

    def test_remove_object(self):
        cc = ChunkMicroCache(1024)
        cc.put("obj1", 0, b"a")
        cc.put("obj1", 1, b"b")
        cc.put("obj2", 0, b"c")
        cc.remove_object("obj1")
        assert cc.get("obj1", 0) is None
        assert cc.get("obj1", 1) is None
        assert cc.get("obj2", 0) == b"c"
        assert cc.count() == 1

    def test_close_clears(self):
        cc = ChunkMicroCache(1024)
        cc.put("o", 0, b"data")
        cc.close()
        assert cc.count() == 0
        assert cc.size() == 0


class TestSeekCacheE2E:
    """End-to-end through /f/{id} with the FakeBackend call counter."""

    def test_repeat_seek_inside_chunk_no_backend_call(self, backend, client, small_payload_app):
        obj, url = small_payload_app
        # first seek into chunk 0 → exactly one backend open
        opens = backend.open_calls
        r = _get_range(client, url, 100, 199)
        assert r.status_code == 206 and r.content == PAYLOAD[100:200]
        assert backend.open_calls == opens + 1
        # second seek in the SAME chunk → served from RAM, zero backend calls
        r2 = _get_range(client, url, 5000, 5099)
        assert r2.status_code == 206 and r2.content == PAYLOAD[5000:5100]
        assert backend.open_calls == opens + 1  # unchanged!

    def test_seek_into_second_chunk_still_correct(self, backend, client, small_payload_app):
        obj, url = small_payload_app
        start = CHUNK + 10  # inside chunk 1
        r = _get_range(client, url, start, start + 99)
        assert r.status_code == 206
        assert r.content == PAYLOAD[start : start + 100]

    def test_admin_status_reports_chunk_cache(self, backend, client, small_payload_app):
        obj, url = small_payload_app
        _get_range(client, url, 0, 1023)
        _get_range(client, url, 100, 1123)  # hit
        r = client.get(
            "/api/v1/admin/status", headers={"Authorization": "Bearer test-admin-key"}
        )
        assert r.status_code == 200
        cc = r.json()["chunk_cache"]
        assert cc["enabled"] is True
        assert cc["entries"] == 1
        assert cc["hits"] == 1
        assert cc["misses"] == 1

    def test_disabled_after_runtime_override(self, backend, client, small_payload_app):
        """seek_cache_mb=0 (runtime override) → every seek hits the backend."""
        obj, url = small_payload_app
        r = client.post(
            "/api/v1/admin/settings",
            json={"seek_cache_mb": 0},
            headers={"Authorization": "Bearer test-admin-key"},
        )
        assert r.status_code == 200
        opens = backend.open_calls
        assert _get_range(client, url, 100, 199).status_code == 206
        assert backend.open_calls == opens + 1
        assert _get_range(client, url, 200, 299).status_code == 206
        assert backend.open_calls == opens + 2  # no caching — both went through

    def test_delete_purges_cached_chunks(self, backend, client, small_payload_app):
        obj, url = small_payload_app
        _get_range(client, url, 0, 1023)  # populate micro cache
        r = client.delete(f"/f/{obj}", headers={"Authorization": "Bearer test-admin-key"})
        assert r.status_code == 200
        status = client.get(
            "/api/v1/admin/status", headers={"Authorization": "Bearer test-admin-key"}
        ).json()
        assert status["chunk_cache"]["entries"] == 0

    def test_full_download_response_bytes_unchanged(self, backend, client, small_payload_app):
        """Byte-exactness guard: ranged reads stay correct with cache on."""
        obj, url = small_payload_app
        ranges = (
            (0, 1023),
            (CHUNK - 100, CHUNK + 100),
            (len(PAYLOAD) - 50, len(PAYLOAD) - 1),
        )
        for start, end in ranges:
            r = _get_range(client, url, start, end)
            assert r.status_code == 206
            assert r.content == PAYLOAD[start : end + 1]
        r = client.get(url)  # full download still byte-exact
        assert r.status_code == 200
        assert r.content == PAYLOAD
