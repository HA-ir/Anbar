"""F3: download streaming + Range semantics against a real (fake) backend."""
from __future__ import annotations

import hashlib

CHUNK = 16 * 1024 * 1024
# 3 chunks: 16MB + 16MB + 3MB
PAYLOAD = (
    bytes(range(256)) * (CHUNK // 256)
    + bytes(range(256)) * (CHUNK // 256)
    + bytes(range(256)) * (3 * 1024 * 1024 // 256)
)
PAYLOAD = PAYLOAD[: 2 * CHUNK + 3 * 1024 * 1024]
SHA = hashlib.sha256(PAYLOAD).hexdigest()


def _upload(client) -> str:
    r = client.post(
        "/api/v1/upload",
        files={"file": ("three.bin", PAYLOAD, "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_full_download(backend, client):
    obj = _upload(client)
    r = client.get(f"/f/{obj}")
    assert r.status_code == 200
    assert r.headers["content-length"] == str(len(PAYLOAD))
    assert r.headers["accept-ranges"] == "bytes"
    assert r.headers["content-disposition"].endswith('filename="three.bin"')
    assert r.content == PAYLOAD


def test_range_inside_single_chunk(backend, client):
    obj = _upload(client)
    r = client.get(f"/f/{obj}", headers={"Range": "bytes=100-199"})
    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes 100-199/{len(PAYLOAD)}"
    assert r.content == PAYLOAD[100:200]


def test_range_across_two_chunks(backend, client):
    obj = _upload(client)
    start = CHUNK - 512
    end = CHUNK + 511
    r = client.get(f"/f/{obj}", headers={"Range": f"bytes={start}-{end}"})
    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes {start}-{end}/{len(PAYLOAD)}"
    assert len(r.content) == 1024
    assert r.content == PAYLOAD[start : end + 1]


def test_range_spanning_all_three_chunks(backend, client):
    obj = _upload(client)
    start = CHUNK - 1
    end = 2 * CHUNK
    r = client.get(f"/f/{obj}", headers={"Range": f"bytes={start}-{end}"})
    assert r.status_code == 206
    assert r.content == PAYLOAD[start : end + 1]


def test_open_ended_range(backend, client):
    obj = _upload(client)
    n = len(PAYLOAD)
    r = client.get(f"/f/{obj}", headers={"Range": f"bytes={n - 10}-"})
    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes {n - 10}-{n - 1}/{n}"
    assert r.content == PAYLOAD[-10:]


def test_suffix_range(backend, client):
    obj = _upload(client)
    r = client.get(f"/f/{obj}", headers={"Range": "bytes=-42"})
    assert r.status_code == 206
    assert r.content == PAYLOAD[-42:]


def test_invalid_ranges(backend, client):
    obj = _upload(client)
    assert client.get(f"/f/{obj}", headers={"Range": "bytes=99999999999-"}).status_code == 416
    assert client.get(f"/f/{obj}", headers={"Range": "bytes=500-100"}).status_code == 416
    assert client.get(f"/f/{obj}", headers={"Range": "nonsense"}).status_code == 416
    assert client.get(f"/f/{obj}", headers={"Range": "bytes=-0"}).status_code == 416


def test_download_not_found(backend, client):
    assert client.get("/f/doesnotexist").status_code == 404
    assert client.get("/f/doesnotexist/info").status_code == 404


def test_info(backend, client):
    obj = _upload(client)
    r = client.get(f"/f/{obj}/info")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == obj
    assert body["size"] == len(PAYLOAD)
    assert body["sha256"] == SHA
    assert body["chunks"] == 3
    assert body["filename"] == "three.bin"


def test_download_chunk_cache_reuse(backend, client):
    """Two overlapping requests for the same object must not re-fetch
    already-fetched chunks *within* a single request; across requests the
    backend is hit again (by design — no persistence in F3)."""
    obj = _upload(client)
    opens_before = backend.open_calls
    client.get(f"/f/{obj}", headers={"Range": f"bytes={CHUNK - 100}-{CHUNK + 100}"})
    # spans chunk 0 and chunk 1 → exactly 2 opens
    assert backend.open_calls == opens_before + 2