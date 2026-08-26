"""F2: object layer — manifest round-trip and range mapping (pure logic)."""

from __future__ import annotations

import pytest

from anbar.objects import Chunk, Manifest, new_object_id


def test_manifest_json_roundtrip():
    m = Manifest(
        chunks=[Chunk(0, 16 * 1024 * 1024, "fid-a"), Chunk(1, 4321, "fid-b")],
        total_size=16 * 1024 * 1024 + 4321,
    )
    m2 = Manifest.from_json(m.to_json())
    assert [c.file_id for c in m2.chunks] == ["fid-a", "fid-b"]
    assert [c.size for c in m2.chunks] == [16 * 1024 * 1024, 4321]
    assert m2.total_size == m.total_size


def test_range_mapping_single_chunk():
    m = Manifest(chunks=[Chunk(0, 100, "a")], total_size=100)
    assert m.map_range(0, 100) == [(0, 0, 100)]
    assert m.map_range(10, 20) == [(0, 10, 10)]
    assert m.map_range(99, 100) == [(0, 99, 1)]


def test_range_mapping_across_chunks():
    m = Manifest(chunks=[Chunk(0, 10, "a"), Chunk(1, 10, "b"), Chunk(2, 10, "c")], total_size=30)
    # spans all three chunks (range ends at 25 → only first 5 bytes of chunk 2)
    assert m.map_range(5, 25) == [(0, 5, 5), (1, 0, 10), (2, 0, 5)]
    assert m.map_range(5, 30) == [(0, 5, 5), (1, 0, 10), (2, 0, 10)]
    # aligned exactly to a chunk boundary
    assert m.map_range(10, 20) == [(1, 0, 10)]
    # partial in middle chunk
    assert m.map_range(12, 15) == [(1, 2, 3)]


def test_range_mapping_out_of_bounds():
    m = Manifest(chunks=[Chunk(0, 10, "a")], total_size=10)
    with pytest.raises(ValueError):
        m.map_range(0, 11)
    with pytest.raises(ValueError):
        m.map_range(-1, 5)


def test_new_object_id_shape():
    seen = {new_object_id() for _ in range(200)}
    assert len(seen) == 200  # no collisions in 200 draws
    for s in seen:
        assert len(s) == 12
        assert s.isalnum()
