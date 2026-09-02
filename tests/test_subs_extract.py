"""FEAT-SUBS-2: embedded subtitle import (MKV soft subs → tracks).

Uses a real ffmpeg-muxed MKV when ffmpeg is available; otherwise verifies
the graceful no-op paths (AVAILABLE=False ⇒ endpoints answer without error).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from anbar import subs_extract
from anbar.objects import Manifest

FFMPEG_MKVIDEO = Path(__file__).parent / "data" / "test_embedded.mkv"

VTT = "WEBVTT\n\n00:01.000 --> 00:02.000\nhi\n"


def _make_fixture_mkv() -> bool:
    """(Re)build the committed test MKV with an embedded Persian sub track."""
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        return False
    data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(exist_ok=True)
    out = FFMPEG_MKVIDEO
    try:
        srt = data_dir / "_tmp_test.fa.srt"
        srt.write_text(
            "1\n00:00:00,500 --> 00:00:01,500\nسلام تست\n\n"
            "2\n00:00:01,600 --> 00:00:02,000\nخط دوم\n",
            encoding="utf-8",
        )
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-f", "lavfi", "-i", "testsrc=duration=2:size=128x64:rate=10",
                "-f", "lavfi", "-i", "sine=duration=2",
                "-i", str(srt),
                "-map", "0:v", "-map", "1:a", "-map", "2:s",
                "-metadata:s:s:0", "language=per",
                "-metadata:s:s:0", "title=Test Persian",
                "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-c:s", "srt",
                str(out),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
        srt.unlink(missing_ok=True)
        return out.exists() and out.stat().st_size > 0
    except Exception:  # noqa: BLE001
        return False


HAVE_MKV = _make_fixture_mkv()


def _upload_video(client, name="clip.mkv"):
    r = client.post(
        "/api/v1/upload",
        files={"file": (name, b"\x00" * 64, "application/octet-stream")},
        headers={"Authorization": "Bearer test-admin-key"},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.mark.skipif(not subs_extract.AVAILABLE, reason="ffmpeg not installed")
@pytest.mark.skipif(not HAVE_MKV, reason="mkv fixture unavailable")
def test_probe_detects_embedded_sub():
    head = FFMPEG_MKVIDEO.read_bytes()
    streams = subs_extract.probe_bytes(head)
    assert len(streams) == 1
    assert streams[0]["codec"] == "subrip"
    assert streams[0]["lang"] == "per"


def test_probe_bytes_garbage():
    assert subs_extract.probe_bytes(b"not a video at all" * 100) == []


def test_video_ext():
    assert subs_extract.video_ext("a.MKV")
    assert subs_extract.video_ext("x/y/movie.mp4")
    assert not subs_extract.video_ext("notes.txt")


def _fake_fetcher_from_fixture():
    data = FFMPEG_MKVIDEO.read_bytes()

    async def fetch_chunk(obj_id, chunk_index, chunk_offset, length):
        blob = data[chunk_offset:] if chunk_offset else data
        return blob[:length] if length else blob

    return fetch_chunk


def _run_import(client, obj_id, fetcher, force):
    """Drive import_embedded with the test client's db/settings."""
    import asyncio

    db = client.app.state.db
    settings = client.app.state.settings
    row = db.get_object(obj_id)
    manifest = Manifest.from_json(row["manifest"]) if row["manifest"] else Manifest()
    loop = asyncio.new_event_loop()
    try:
        import json as _json

        return loop.run_until_complete(
            subs_extract.import_embedded(
                db, settings, obj_id, _json.loads(manifest.to_json()), fetcher, force=force
            )
        )
    finally:
        loop.close()


@pytest.mark.skipif(not subs_extract.AVAILABLE, reason="ffmpeg not installed")
@pytest.mark.skipif(not HAVE_MKV, reason="mkv fixture unavailable")
def test_import_embedded_full_flow(client):
    import time

    r = client.post(
        "/api/v1/upload",
        files={"file": ("real.mkv", FFMPEG_MKVIDEO.read_bytes(), "application/octet-stream")},
        headers={"Authorization": "Bearer test-admin-key"},
    )
    assert r.status_code == 200
    obj_id = r.json()["id"]
    # the background auto-import hook races us — let it settle first
    from anbar import subtitles as _subs

    for _ in range(40):
        if _subs.load(client.app.state.db, obj_id):
            break
        time.sleep(0.1)
    # the hook already imported the track; a repeat import must NOT duplicate
    added = _run_import(client, obj_id, _fake_fetcher_from_fixture(), force=True)
    assert len(added) == 0
    tracks = _subs.load(client.app.state.db, obj_id)
    assert len(tracks) == 1
    assert tracks[0]["lang"] == "fa"  # per → fa normalization
    # served as WebVTT through the public endpoint
    tid = tracks[0]["id"]
    vtt = client.get(f"/f/{obj_id}/subs/{tid}", headers={"Authorization": "Bearer test-admin-key"})
    assert vtt.status_code == 200
    assert "سلام تست" in vtt.text
    # second import without force is a one-shot no-op
    added2 = _run_import(client, obj_id, _fake_fetcher_from_fixture(), force=False)
    assert added2 == []
    # tracks survived
    lst = client.get(
        f"/api/v1/admin/objects/{obj_id}/subs", headers={"Authorization": "Bearer test-admin-key"}
    )
    assert len(lst.json()["tracks"]) == 1


@pytest.mark.skipif(not subs_extract.AVAILABLE, reason="ffmpeg not installed")
@pytest.mark.skipif(not HAVE_MKV, reason="mkv fixture unavailable")
def test_import_skips_existing_lang(client):
    r = client.post(
        "/api/v1/upload",
        files={"file": ("real.mkv", FFMPEG_MKVIDEO.read_bytes(), "application/octet-stream")},
        headers={"Authorization": "Bearer test-admin-key"},
    )
    obj_id = r.json()["id"]
    # pre-create a track with lang=fa so the embedded one is skipped
    client.post(
        f"/api/v1/admin/objects/{obj_id}/subs?lang=fa",
        files={"file": ("fa.srt", VTT.encode(), "text/vtt")},
        headers={"Authorization": "Bearer test-admin-key"},
    )
    added = _run_import(client, obj_id, _fake_fetcher_from_fixture(), force=True)
    assert added == []


def test_import_endpoint_requires_video(client):
    obj_id = _upload_video(client, name="doc.txt")
    r = client.post(
        f"/api/v1/admin/objects/{obj_id}/subs/import-embedded",
        headers={"Authorization": "Bearer test-admin-key"},
    )
    assert r.status_code == 400


def test_subs_extract_enabled_runtime_switch(client):
    """v0.15.41: subs_extract_enabled runtime setting gates auto-import + import endpoint."""
    import time

    from anbar import runtime

    db = client.app.state.db
    assert runtime.get_int(db, "subs_extract_enabled", 1) == 1  # default ON

    # upload a real MKV → bg auto-import fires (flag on) → 1 track
    r = client.post(
        "/api/v1/upload",
        files={"file": ("real.mkv", FFMPEG_MKVIDEO.read_bytes(), "application/octet-stream")},
        headers={"Authorization": "Bearer test-admin-key"},
    )
    assert r.status_code == 200
    obj_id = r.json()["id"]
    from anbar import subtitles as _subs

    for _ in range(40):
        if _subs.load(client.app.state.db, obj_id):
            break
        time.sleep(0.1)
    assert len(_subs.load(client.app.state.db, obj_id)) == 1

    # turn the feature OFF
    r = client.post(
        "/api/v1/admin/settings",
        json={"subs_extract_enabled": 0},
        headers={"Authorization": "Bearer test-admin-key"},
    )
    assert r.status_code == 200
    assert runtime.get_int(db, "subs_extract_enabled", 1) == 0

    # manual import endpoint now refuses with 409
    r2 = client.post(
        f"/api/v1/admin/objects/{obj_id}/subs/import-embedded",
        headers={"Authorization": "Bearer test-admin-key"},
    )
    assert r2.status_code == 409

    # a NEW upload with flag off → no auto-import (one-shot flag still unset)
    r3 = client.post(
        "/api/v1/upload",
        files={"file": ("real2.mkv", FFMPEG_MKVIDEO.read_bytes(), "application/octet-stream")},
        headers={"Authorization": "Bearer test-admin-key"},
    )
    assert r3.status_code == 200
    obj2 = r3.json()["id"]
    time.sleep(1.5)
    assert _subs.load(client.app.state.db, obj2) == []

    # back ON → endpoint works again
    client.post(
        "/api/v1/admin/settings",
        json={"subs_extract_enabled": 1},
        headers={"Authorization": "Bearer test-admin-key"},
    )
    r4 = client.post(
        f"/api/v1/admin/objects/{obj2}/subs/import-embedded",
        headers={"Authorization": "Bearer test-admin-key"},
    )
    assert r4.status_code == 200
    assert len(r4.json()["added"]) == 1
