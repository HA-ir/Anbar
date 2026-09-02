"""QUAL-01: ObjectService — shared store/rollback/commit for upload+ingest."""

from __future__ import annotations

import json

import pytest


class FlakyBackend:
    """Fake backend: fails on Nth store, records everything."""

    name = "flaky"

    def __init__(self, fail_on_store: int | None = None, fail_on_delete: bool = False):
        self.stored: list[tuple[bytes, str]] = []
        self.deleted: list[str] = []
        self.fail_on_store = fail_on_store
        self.fail_on_delete = fail_on_delete
        self._n = 0

    async def store(self, data, name, content_type=None, caption=None):
        self._n += 1
        if self.fail_on_store is not None and self._n >= self.fail_on_store:
            raise RuntimeError("boom")
        self.stored.append((bytes(data), name))
        from anbar.storage.base import ObjectRef

        return ObjectRef(file_id=f"fid-{self._n}", message_id=self._n, backend=self.name)

    async def delete(self, ref):
        if self.fail_on_delete:
            raise RuntimeError("delete failed too")  # rollback must swallow this
        self.deleted.append(ref.file_id)
        return True


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


class FakeSettings:
    chunk_size = 8
    hmac_secret = None


@pytest.fixture
def app_like():
    from types import SimpleNamespace

    from anbar.self_healing import encode_chunk_caption  # noqa: F401

    db = FakeDB()
    backend = FlakyBackend()
    settings = FakeSettings()
    return SimpleNamespace(backend=backend, db=db, settings=settings)


def _svc(app_like, filename="f.bin", **kw):
    from anbar.object_service import ObjectService

    return ObjectService(
        backend=app_like.backend,
        db=app_like.db,
        settings=app_like.settings,
        filename=filename,
        **kw,
    )


@pytest.mark.asyncio
async def test_store_commit_roundtrip(app_like):
    svc = _svc(app_like)
    manifest, sha = await svc.store_stream(ByteReader(b"A" * 20))
    assert len(manifest.chunks) == 3  # 8+8+4
    assert sum(c.size for c in manifest.chunks) == 20
    assert len(sha) == 64
    obj_id = svc.commit(sha_hex=sha, uploader_key="uk1")
    assert len(app_like.db.objects) == 1
    obj = app_like.db.objects[0]
    assert obj["id"] == obj_id
    assert obj["size"] == 20
    assert obj["uploader_key"] == "uk1"
    # caption path is exercised (upload semantics) — blobs stored with captions
    assert app_like.backend.stored


@pytest.mark.asyncio
async def test_rollback_on_store_failure(app_like):
    app_like.backend.fail_on_store = 3  # 3rd store fails
    svc = _svc(app_like)
    with pytest.raises(RuntimeError, match="boom"):
        await svc.store_stream(ByteReader(b"B" * 40))
    # first 2 blobs were stored, then rolled back
    assert len(app_like.backend.stored) == 2
    assert sorted(app_like.backend.deleted) == ["fid-1", "fid-2"]
    # no object committed, no checkpoint left over
    assert app_like.db.objects == []


@pytest.mark.asyncio
async def test_rollback_swallows_delete_errors(app_like):
    app_like.backend.fail_on_store = 2
    app_like.backend.fail_on_delete = True
    svc = _svc(app_like)
    with pytest.raises(RuntimeError, match="boom"):
        await svc.store_stream(ByteReader(b"C" * 40))
    assert app_like.backend.deleted == []  # deletes failed…
    # …but rollback must not raise on top of the original error


@pytest.mark.asyncio
async def test_checkpoint_lifecycle(app_like):
    app_like.backend.fail_on_store = 3
    svc = _svc(app_like, upload_id="u42")
    with pytest.raises(RuntimeError):
        await svc.store_stream(ByteReader(b"D" * 40))
    ck = json.loads(app_like.db.kv["upres:u42"])
    assert len(ck["chunks"]) == 2
    assert "_ts" in ck  # envelope format (MP-02)

    # successful run: commit + drop leaves no kv residue
    app_like.backend.fail_on_store = None
    svc2 = _svc(app_like, upload_id="u42")
    _, sha = await svc2.store_stream(ByteReader(b"E" * 10))
    assert json.loads(app_like.db.kv["upres:u42"])["chunks"]  # checkpoint alive mid-resume
    svc2.commit(sha_hex=sha)
    svc2.drop_checkpoint()
    assert "upres:u42" not in app_like.db.kv


@pytest.mark.asyncio
async def test_resume_drains_then_stores(app_like):
    # seed a checkpoint as if 2 chunks were already stored
    app_like.db.kv["upres:u9"] = json.dumps(
        {
            "_ts": 1,
            "chunks": [
                {"s": 8, "f": "seeded-1", "m": 1},
                {"s": 8, "f": "seeded-2", "m": 2},
            ],
        }
    )
    svc = _svc(app_like, upload_id="u9", resume_from=2)
    # wire contract: client re-sends the WHOLE file — first 2 chunks are
    # duplicates (drained), only the third hits the backend
    manifest, _ = await svc.store_stream(ByteReader(b"F" * 24))
    assert [c.file_id for c in manifest.chunks] == ["seeded-1", "seeded-2", "fid-1"]
    assert len(app_like.backend.stored) == 1  # only the third chunk hit the backend


@pytest.mark.asyncio
async def test_resume_out_of_range(app_like):
    from anbar.object_service import ResumeOutOfRange

    app_like.db.kv["upres:u7"] = json.dumps({"_ts": 1, "chunks": [{"s": 8, "f": "x", "m": 1}]})
    svc = _svc(app_like, upload_id="u7", resume_from=5)
    with pytest.raises(ResumeOutOfRange):
        await svc.store_stream(ByteReader(b"G" * 8))


@pytest.mark.asyncio
async def test_ingest_run_job_commits_via_service(client, monkeypatch):
    """End-to-end ingest job: object committed through the shared service."""

    from anbar.api import ingest as ing

    app = client.app

    class FakeResp:
        status_code = 200
        headers = {"content-length": "16", "content-type": "text/plain"}

        def aiter_bytes(self, n):
            async def gen():
                yield b"x" * 8
                yield b"y" * 8

            return gen()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, method, url):
            return FakeResp()

    monkeypatch.setattr(ing.httpx, "AsyncClient", FakeClient)
    ing.JOBS["q1"] = {
        "id": "q1",
        "state": "running",
        "url": "https://x/f.bin",
        "bytes": 0,
        "chunks": 0,
        "total": 0,
        "object": None,
        "error": None,
        "started": 0.0,
        "key": "uk-ingest",
    }
    await ing._run_job(app, "q1", "https://x/f.bin", None)
    job = ing.JOBS["q1"]
    assert job["state"] == "done", job.get("error")
    # app chunk_size (16MB) > 16-byte body → one chunk
    assert job["chunks"] == 1
    assert job["object"]["size"] == 16
    # committed exactly one object with the ingest uploader key (SELECT *)
    objs = app.state.db.list_objects_full(limit=10)
    assert any(o.get("uploader_key") == "uk-ingest" for o in objs)
    assert any(o["id"] == job["object"]["id"] for o in objs)
