"""Tests for BUG-33: large MKV and video file preview, Range requests, and Content-Type."""

from __future__ import annotations

from pathlib import Path
import pytest

AUTH = {"Authorization": "Bearer test-key"}
ADMIN = {"Authorization": "Bearer test-admin-key"}
FIXTURE_MKV = Path(__file__).parent / "data" / "test_embedded.mkv"

def _get_mkv_bytes() -> bytes:
    if FIXTURE_MKV.exists():
        return FIXTURE_MKV.read_bytes()
    return b"MKV_HEADER" + b"X" * 50000

def test_mkv_upload_and_content_type(backend, client):
    mkv_bytes = _get_mkv_bytes()
    filename = "The.Mentalist.S01E01.720p.BluRay.Farsi.Sub.Film2Media.mkv"

    # Upload with application/octet-stream to simulate browser/curl default
    r = client.post(
        "/api/v1/upload",
        files={"file": (filename, mkv_bytes, "application/octet-stream")},
        headers=AUTH,
    )
    assert r.status_code == 200, r.text
    obj_id = r.json()["id"]

    # Verify info endpoint reports video/x-matroska
    r_info = client.get(f"/f/{obj_id}/info", headers=AUTH)
    assert r_info.status_code == 200
    assert r_info.json()["content_type"] == "video/x-matroska"

    # Verify GET /f/{obj_id} serves video/x-matroska with inline disposition and Accept-Ranges
    r_dl = client.get(f"/f/{obj_id}", headers=AUTH)
    assert r_dl.status_code == 200
    assert r_dl.headers["content-type"] == "video/x-matroska"
    assert "inline" in r_dl.headers["content-disposition"]
    assert r_dl.headers["accept-ranges"] == "bytes"
    assert r_dl.content == mkv_bytes

def test_mkv_range_requests(backend, client):
    mkv_bytes = _get_mkv_bytes()
    total = len(mkv_bytes)
    filename = "sample.mkv"

    r = client.post(
        "/api/v1/upload",
        files={"file": (filename, mkv_bytes, "application/octet-stream")},
        headers=AUTH,
    )
    assert r.status_code == 200
    obj_id = r.json()["id"]

    # Range start-end
    r_range = client.get(f"/f/{obj_id}", headers={**AUTH, "Range": "bytes=0-1023"})
    assert r_range.status_code == 206
    assert r_range.headers["content-range"] == f"bytes 0-1023/{total}"
    assert r_range.headers["content-type"] == "video/x-matroska"
    assert r_range.headers["accept-ranges"] == "bytes"
    assert len(r_range.content) == 1024
    assert r_range.content == mkv_bytes[0:1024]

    # Range seeking into middle
    r_range_mid = client.get(f"/f/{obj_id}", headers={**AUTH, "Range": "bytes=1000-1999"})
    assert r_range_mid.status_code == 206
    assert r_range_mid.headers["content-range"] == f"bytes 1000-1999/{total}"
    assert len(r_range_mid.content) == 1000
    assert r_range_mid.content == mkv_bytes[1000:2000]

    # Open-ended Range
    r_open = client.get(f"/f/{obj_id}", headers={**AUTH, "Range": "bytes=2000-"})
    assert r_open.status_code == 206
    assert r_open.headers["content-range"] == f"bytes 2000-{total - 1}/{total}"
    assert r_open.content == mkv_bytes[2000:]

    # Suffix Range
    r_suffix = client.get(f"/f/{obj_id}", headers={**AUTH, "Range": "bytes=-500"})
    assert r_suffix.status_code == 206
    assert r_suffix.headers["content-range"] == f"bytes {total - 500}-{total - 1}/{total}"
    assert r_suffix.content == mkv_bytes[-500:]

def test_mkv_head_request(backend, client):
    mkv_bytes = _get_mkv_bytes()
    total = len(mkv_bytes)
    r = client.post(
        "/api/v1/upload",
        files={"file": ("head_test.mkv", mkv_bytes, "video/x-matroska")},
        headers=AUTH,
    )
    assert r.status_code == 200
    obj_id = r.json()["id"]

    # HEAD full
    r_head = client.head(f"/f/{obj_id}", headers=AUTH)
    assert r_head.status_code == 200
    assert r_head.headers["content-type"] == "video/x-matroska"
    assert r_head.headers["content-length"] == str(total)
    assert r_head.headers["accept-ranges"] == "bytes"
    assert len(r_head.content) == 0

    # HEAD with Range
    r_head_range = client.head(f"/f/{obj_id}", headers={**AUTH, "Range": "bytes=0-99"})
    assert r_head_range.status_code == 206
    assert r_head_range.headers["content-range"] == f"bytes 0-99/{total}"
    assert r_head_range.headers["content-length"] == "100"
    assert len(r_head_range.content) == 0

def test_no_regression_mp4_webm(backend, client):
    for fn, ct in [("video.mp4", "video/mp4"), ("video.webm", "video/webm")]:
        data = b"test video content " * 500
        r = client.post(
            "/api/v1/upload",
            files={"file": (fn, data, "application/octet-stream")},
            headers=AUTH,
        )
        assert r.status_code == 200
        obj_id = r.json()["id"]

        # Check full
        r_get = client.get(f"/f/{obj_id}", headers=AUTH)
        assert r_get.status_code == 200
        assert r_get.headers["content-type"] == ct
        assert "inline" in r_get.headers["content-disposition"]
        assert r_get.headers["accept-ranges"] == "bytes"

        # Check range
        r_range = client.get(f"/f/{obj_id}", headers={**AUTH, "Range": "bytes=10-49"})
        assert r_range.status_code == 206
        assert r_range.headers["content-range"] == f"bytes 10-49/{len(data)}"
        assert r_range.content == data[10:50]

def test_mkv_cached_range_seeking(backend, client):
    mkv_bytes = _get_mkv_bytes()
    total = len(mkv_bytes)
    r = client.post(
        "/api/v1/upload",
        files={"file": ("cached_sample.mkv", mkv_bytes, "application/octet-stream")},
        headers=AUTH,
    )
    assert r.status_code == 200
    obj_id = r.json()["id"]

    # First do a full GET to populate disk cache
    r_full = client.get(f"/f/{obj_id}", headers=AUTH)
    assert r_full.status_code == 200

    # Range request after cache
    r_range = client.get(f"/f/{obj_id}", headers={**AUTH, "Range": "bytes=500-1500"})
    assert r_range.status_code == 206
    assert r_range.headers["content-range"] == f"bytes 500-1500/{total}"
    assert r_range.content == mkv_bytes[500:1501]
