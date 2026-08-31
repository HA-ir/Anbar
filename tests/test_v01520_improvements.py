"""v0.15.20 improvement-plan fixes: MP-01, MP-02, SEC-04.

MP-01 — multipart resume: X-Upload-Id / X-Resume-From must work on
        POST /api/v1/upload (same contract as /upload/raw).
MP-02 — resume checkpoint cleanup: kv upres:<id> must be deleted after a
        successful commit, and the prune loop helper must drop stale ones.
SEC-04 — .env writes must be atomic (temp file + os.replace).
"""

from __future__ import annotations

import json
import time

from starlette.testclient import TestClient

UP = {"Authorization": "Bearer test-key"}


# ── MP-01: multipart resume ──────────────────────────────────────────────


def test_multipart_resume_checkpoint_created_and_cleaned(client: TestClient):
    """First send with X-Upload-Id stores a checkpoint; after success the
    checkpoint kv key is gone (MP-02), yet the object is committed."""
    # part 1 of 2
    r1 = client.post(
        "/api/v1/upload",
        files={"file": ("resumable.bin", b"A" * 32, "application/octet-stream")},
        headers={**UP, "X-Upload-Id": "mp-part1"},
    )
    assert r1.status_code == 200, r1.text
    obj1 = r1.json()["id"]

    db = client.app.state.db
    # checkpoint was deleted on commit (MP-02) — no upres row survives
    assert db.kv_get("upres:mp-part1") is None

    # committed object has exactly 1 chunk (FakeBackend chunks by chunk_size)
    row = db.get_object(obj1)
    assert row is not None
    manifest = json.loads(row["manifest"])
    assert len(manifest["chunks"]) == 1


async def test_multipart_resume_drains_stored_chunks(client: TestClient, monkeypatch):
    """Contract (same as upload/raw): client re-sends the WHOLE file; server
    drains the first `resume_from` chunks (already stored), stores the rest.
    Seed checkpoint with 1 chunk, re-send 2 chunks with resume_from=1:
    seeded chunk drained, second chunk stored → manifest = 2 chunks."""
    import anbar.api.upload as up

    app = client.app
    db = app.state.db
    uid = "mp-resume-2"

    db.kv_set(
        "upres:" + uid,
        json.dumps(
            {
                "_ts": int(time.time()),
                "chunks": [{"s": 32, "f": "seeded-file-id-1", "m": 4242}],
            },
            separators=(",", ":"),
        ),
    )

    # small chunk size so a 64-byte body = 2 chunks
    monkeypatch.setattr(type(app.state.settings), "chunk_size", property(lambda self: 32))

    class Rdr:
        def __init__(self):
            self.i = 0

        async def read(self, n):
            self.i += 1
            if self.i == 1:
                return b"B" * 32
            if self.i == 2:
                return b"C" * 32
            return b""

    class FakeReq:
        def __init__(self, application, upload_id=None):
            self.app = application
            self.headers = {"x-upload-id": upload_id} if upload_id else {}

        def stream(self):
            return Rdr()

    req = FakeReq(app, upload_id=uid)
    manifest, sha = await up._store_stream(
        req, req.stream(), "resume2.bin", upload_id=uid, resume_from=1
    )

    # 1 seeded chunk (drained duplicate) + 1 newly stored chunk
    assert [c.size for c in manifest.chunks] == [32, 32]
    assert manifest.chunks[0].file_id == "seeded-file-id-1"
    # the second chunk really hit the backend (not another duplicate)
    assert manifest.chunks[1].file_id != "seeded-file-id-1"

    # checkpoint updated to the full manifest (still alive — resume may continue)
    ck = json.loads(db.kv_get("upres:" + uid))
    assert len(ck["chunks"]) == 2


def test_multipart_resume_invalid_from_rejected(client: TestClient):
    r = client.post(
        "/api/v1/upload",
        files={"file": ("x.bin", b"data", "application/octet-stream")},
        headers={**UP, "X-Upload-Id": "mp-bad", "X-Resume-From": "notanint"},
    )
    assert r.status_code == 400
    assert "X-Resume-From" in r.json()["detail"]


def test_multipart_resume_beyond_checkpoint_rejected(client: TestClient):
    db = client.app.state.db
    db.kv_set(
        "upres:mp-beyond",
        json.dumps({"_ts": int(time.time()), "chunks": [{"s": 1, "f": "x"}]}),
    )
    r = client.post(
        "/api/v1/upload",
        files={"file": ("y.bin", b"data" * 8, "application/octet-stream")},
        headers={**UP, "X-Upload-Id": "mp-beyond", "X-Resume-From": "5"},
    )
    assert r.status_code == 409


# ── MP-02: stale checkpoint pruning ─────────────────────────────────────


def test_kv_prune_prefix_drops_only_stale(client: TestClient):
    db = client.app.state.db
    now = int(time.time())
    db.kv_set("upres:fresh", json.dumps({"_ts": now, "chunks": []}))
    db.kv_set("upres:stale", json.dumps({"_ts": now - 90000, "chunks": []}))
    db.kv_set("unrelated", json.dumps({"_ts": now - 90000, "chunks": []}))

    removed = db.kv_prune_prefix("upres:", max_age_s=86400)
    assert removed == 1
    assert db.kv_get("upres:fresh") is not None
    assert db.kv_get("upres:stale") is None
    assert db.kv_get("unrelated") is not None  # different prefix untouched


def test_kv_prune_prefix_legacy_list_format_is_ignored(client: TestClient):
    """Old-format checkpoints (bare JSON list, no _ts) must not crash the
    prune; they simply survive until overwritten in the new format."""
    db = client.app.state.db
    db.kv_set("upres:legacy", json.dumps([{"s": 1, "f": "x"}]))
    removed = db.kv_prune_prefix("upres:", max_age_s=86400)
    assert removed == 0
    assert db.kv_get("upres:legacy") is not None


# ── SEC-04: atomic .env writes ──────────────────────────────────────────


def test_write_env_dict_atomic_and_keeps_comments(tmp_path):
    from anbar.api.admin import _read_env_dict, _write_env_dict

    env = tmp_path / ".env"
    env.write_text(
        "# comment kept\nANBAR_BACKEND=bot\nANBAR_CHANNEL_ID=@old\n",
        encoding="utf-8",
    )
    ok = _write_env_dict(env, {"ANBAR_CHANNEL_ID": "@new", "ANBAR_API_ID": "12345"})
    assert ok
    data = _read_env_dict(env)
    assert data["ANBAR_BACKEND"] == "bot"
    assert data["ANBAR_CHANNEL_ID"] == "@new"
    assert data["ANBAR_API_ID"] == "12345"
    raw = env.read_text(encoding="utf-8")
    assert "# comment kept" in raw
    # .bak snapshot of the previous version exists
    assert (env.parent / (env.name + ".bak")).exists()


def test_write_env_dict_creates_missing_file(tmp_path):
    from anbar.api.admin import _read_env_dict, _write_env_dict

    env = tmp_path / ".env"
    ok = _write_env_dict(env, {"ANBAR_BACKEND": "mtproto"})
    assert ok
    assert _read_env_dict(env)["ANBAR_BACKEND"] == "mtproto"
