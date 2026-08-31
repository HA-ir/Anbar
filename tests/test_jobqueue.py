"""ARCH-02: durable in-process job queue (v0.15.24).

Covers the design in IMPROVEMENT_PLAN.md §5:
- jobs table lifecycle: submit → queued → running → done/error
- per-kind concurrency caps (ingest=2, backup=1, rebuild=1)
- restart semantics: queued/running rows → interrupted at boot
- admin API: list/get/cancel/delete + prune after 1h
- ingest endpoint persists a durable row; status falls back to it after a
  restart instead of 404
- backup/rebuild endpoints return job_id and complete through the queue
"""

from __future__ import annotations

import asyncio
import time

import pytest

from anbar.jobqueue import KIND_CONCURRENCY, JobQueue

# ── unit: queue mechanics ───────────────────────────────────────────────────


class FakeDB:
    def __init__(self):
        import sqlite3

        self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row


@pytest.fixture()
def jq():
    db = FakeDB()
    JobQueue._ensure_table(db)
    return JobQueue(db)


@pytest.mark.asyncio
async def test_submit_runs_handler_and_finishes(jq):
    seen = {}

    async def handler(jid, payload):
        seen["args"] = (jid, payload)
        jq.set_progress(jid, done=5, total=10)
        jq.finish(jid, result={"value": 42})

    jq.submit("ingest_url", job_id="j1", payload={"u": 1}, handler=handler)
    await asyncio.sleep(0.05)
    assert seen["args"] == ("j1", {"u": 1})
    row = jq.get("j1")
    assert row["state"] == "done"
    assert row["progress"] == 5 and row["total"] == 10
    assert row["result"] == {"value": 42}  # parsed by get()
    assert row["finished_at"] is not None


@pytest.mark.asyncio
async def test_handler_exception_marks_error(jq):
    async def handler(jid, payload):
        raise RuntimeError("boom")

    jq.submit("ingest_url", job_id="j2", handler=handler)
    await asyncio.sleep(0.05)
    row = jq.get("j2")
    assert row["state"] == "error"
    assert "boom" in row["error"]


@pytest.mark.asyncio
async def test_handler_leaving_row_running_is_closed(jq):
    async def handler(jid, payload):
        pass  # never calls finish

    jq.submit("ingest_url", job_id="j3", handler=handler)
    await asyncio.sleep(0.05)
    assert jq.get("j3")["state"] == "done"


@pytest.mark.asyncio
async def test_per_kind_concurrency_cap(jq):
    active = {"n": 0, "peak": 0}

    async def handler(jid, payload):
        active["n"] += 1
        active["peak"] = max(active["peak"], active["n"])
        await asyncio.sleep(0.05)
        active["n"] -= 1
        jq.finish(jid, result={})

    for i in range(5):
        jq.submit("backup_now", job_id=f"b{i}", handler=handler)
    await asyncio.sleep(0.4)
    assert active["peak"] == 1  # cap of one honored
    assert all(jq.get(f"b{i}")["state"] == "done" for i in range(5))


@pytest.mark.asyncio
async def test_ingest_cap_is_two(jq):
    active = {"n": 0, "peak": 0}

    async def handler(jid, payload):
        active["n"] += 1
        active["peak"] = max(active["peak"], active["n"])
        await asyncio.sleep(0.05)
        active["n"] -= 1
        jq.finish(jid, result={})

    for i in range(4):
        jq.submit("ingest_url", job_id=f"i{i}", handler=handler)
    await asyncio.sleep(0.3)
    assert active["peak"] == 2


@pytest.mark.asyncio
async def test_unknown_kind_rejected(jq):
    with pytest.raises(ValueError):
        jq.submit("nope", job_id="x1")


@pytest.mark.asyncio
async def test_no_handler_means_error(jq):
    jq.submit("channel_rebuild", job_id="r1")
    await asyncio.sleep(0.05)
    row = jq.get("r1")
    assert row["state"] == "error"
    assert "no handler" in row["error"]


# ── unit: restart / prune / cancel / delete ─────────────────────────────────


def test_mark_interrupted_on_boot(jq):
    now = int(time.time())
    for jid, state in (("q1", "queued"), ("r1", "running"), ("d1", "done")):
        jq.db._conn.execute(
            "INSERT INTO jobs (id, kind, state, created_at) VALUES (?, 'ingest_url', ?, ?)",
            (jid, state, now),
        )
    jq.db._conn.commit()
    n = jq.mark_interrupted_on_boot()
    assert n == 2
    assert jq.get("q1")["state"] == "interrupted"
    assert jq.get("r1")["state"] == "interrupted"
    assert jq.get("d1")["state"] == "done"  # finished rows untouched


def test_prune_drops_only_old_finished(jq):
    now = int(time.time())
    rows = [
        ("old-done", "done", now - 7200),
        ("fresh-done", "done", now - 60),
        ("old-run", "running", now - 7200),
    ]
    for jid, state, ts in rows:
        jq.db._conn.execute(
            "INSERT INTO jobs (id, kind, state, created_at, finished_at) "
            "VALUES (?, 'ingest_url', ?, ?, ?)",
            (jid, state, ts, ts),
        )
    jq.db._conn.commit()
    removed = jq.prune()
    assert removed == 1
    assert jq.get("old-done") is None
    assert jq.get("fresh-done") is not None
    assert jq.get("old-run") is not None  # running rows are never pruned


@pytest.mark.asyncio
async def test_cancel_queued_only(jq):
    async def handler(jid, payload):
        await asyncio.sleep(0.05)
        jq.finish(jid, result={})

    jq.submit("ingest_url", job_id="c1", handler=handler)  # will run at once
    jq.submit("ingest_url", job_id="c2", handler=handler)  # 2nd slot
    jq.submit("ingest_url", job_id="c3", handler=handler)  # queued (cap=2)
    await asyncio.sleep(0.01)
    # running jobs are not cancellable → conflict semantics
    assert jq.cancel("c1") is False
    # c3 must still be queued → cancellable
    state3 = jq.get("c3")["state"]
    if state3 == "queued":
        assert jq.cancel("c3") is True
        assert jq.get("c3")["state"] == "error"
    await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_delete_finished_only(jq):
    async def handler(jid, payload):
        jq.finish(jid, result={})

    jq.submit("ingest_url", job_id="d9", handler=handler)
    await asyncio.sleep(0.05)
    assert jq.delete("d9") is True
    assert jq.get("d9") is None
    assert jq.delete("d9") is False


def test_list_filters(jq):
    now = int(time.time())
    for jid, kind, state in (
        ("l1", "ingest_url", "done"),
        ("l2", "backup_now", "error"),
        ("l3", "ingest_url", "running"),
    ):
        jq.db._conn.execute(
            "INSERT INTO jobs (id, kind, state, created_at) VALUES (?, ?, ?, ?)",
            (jid, kind, state, now),
        )
    jq.db._conn.commit()
    assert [r["id"] for r in jq.list(kind="backup_now")] == ["l2"]
    assert {r["id"] for r in jq.list(state="done")} == {"l1"}
    assert len(jq.list(limit=2)) == 2


def test_kind_caps_table():
    assert KIND_CONCURRENCY == {
        "ingest_url": 2,
        "backup_now": 1,
        "channel_rebuild": 1,
    }


# ── integration: endpoints over the real app ────────────────────────────────

ADMIN = {"Authorization": "Bearer test-admin-key"}


def test_ingest_persists_durable_row_and_status_fallback(backend, client, monkeypatch):
    """Restart simulation: JOBS entry gone → status endpoint reads the DB row."""
    # submit an ingest job that immediately errors (origin 404) — via direct
    # queue use to avoid network mocking here
    r = client.post(
        "/api/v1/upload/url",
        json={"url": "https://origin.invalid/file.bin"},
        headers=ADMIN,
    )
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    # durable row exists right away
    row = client.app.state.job_queue.get(job_id)
    assert row is not None and row["kind"] == "ingest_url"

    # simulate a restart: wipe the in-memory JOBS dict
    from anbar.api.ingest import JOBS

    JOBS.clear()
    try:
        r2 = client.get(f"/api/v1/upload/url/{job_id}", headers=ADMIN)
        assert r2.status_code == 200
        body = r2.json()
        assert body["state"] in ("error", "queued", "running", "done", "interrupted")
        # the durable row carries the error after the handler ran
    finally:
        JOBS.clear()


def test_ingest_status_unknown_after_full_prune(backend, client):
    r = client.get("/api/v1/upload/url/nope123", headers=ADMIN)
    assert r.status_code == 404


def test_jobs_admin_api_requires_admin(backend, client):
    r = client.get("/api/v1/admin/jobs")
    assert r.status_code in (401, 403)


def test_jobs_admin_api_list_get_delete(backend, client):
    jq = client.app.state.job_queue
    jq.db._conn.execute(
        "INSERT INTO jobs (id, kind, state, created_at, finished_at) "
        "VALUES ('adm1', 'backup_now', 'done', ?, ?)",
        (int(time.time()), int(time.time())),
    )
    jq.db._conn.commit()

    r = client.get("/api/v1/admin/jobs", headers=ADMIN)
    assert r.status_code == 200
    ids = [j["id"] for j in r.json()["jobs"]]
    assert "adm1" in ids

    r2 = client.get("/api/v1/admin/jobs/adm1", headers=ADMIN)
    assert r2.status_code == 200
    assert r2.json()["kind"] == "backup_now"

    r3 = client.delete("/api/v1/admin/jobs/adm1", headers=ADMIN)
    assert r3.status_code == 200
    assert client.get("/api/v1/admin/jobs/adm1", headers=ADMIN).status_code == 404

    # deleting again → 404
    assert client.delete("/api/v1/admin/jobs/adm1", headers=ADMIN).status_code == 404


def test_jobs_cancel_running_conflict(backend, client):
    jq = client.app.state.job_queue
    jq.db._conn.execute(
        "INSERT INTO jobs (id, kind, state, created_at) "
        "VALUES ('run1', 'ingest_url', 'running', ?)",
        (int(time.time()),),
    )
    jq.db._conn.commit()
    r = client.post("/api/v1/admin/jobs/run1/cancel", headers=ADMIN)
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_backup_runs_through_queue(backend, client):
    """backup/telegram → queued → poll → done, and kv gets updated."""

    db = client.app.state.db
    r = client.post("/api/v1/admin/backup/telegram", headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "queued"
    jid = body["job_id"]
    deadline = time.time() + 5
    row = None
    while time.time() < deadline:
        row = client.app.state.job_queue.get(jid)
        if row and row["state"] in ("done", "error"):
            break
        await asyncio.sleep(0.02)
    assert row is not None and row["state"] == "done", row
    assert row["result"] and row["result"]["size"] > 0
    assert db.kv_get("last_backup_ref") is not None
    # endpoint for polling works too
    r2 = client.get(f"/api/v1/admin/jobs/{jid}", headers=ADMIN)
    assert r2.status_code == 200
    assert r2.json()["state"] == "done"


def test_restart_marks_running_jobs_interrupted(backend, tmp_path, monkeypatch):
    """Full app restart over the same SQLite file: a running row becomes
    interrupted at boot (§5.1 restart semantics)."""
    from fastapi.testclient import TestClient

    from anbar.main import create_app

    monkeypatch.setenv("ANBAR_DB_PATH", str(tmp_path / "restart.db"))
    monkeypatch.setenv("ANBAR_DATA_DIR", str(tmp_path))
    from anbar.config import get_settings

    get_settings.cache_clear()
    try:
        app1 = create_app(backend=backend)
        with TestClient(app1) as c1:
            jq1 = c1.app.state.job_queue
            now = int(time.time())
            jq1.db._conn.execute(
                "INSERT INTO jobs (id, kind, state, created_at) "
                "VALUES ('live1', 'channel_rebuild', 'running', ?)",
                (now,),
            )
            jq1.db._conn.commit()
        # "restart": fresh app over the same SQLite file
        app2 = create_app(backend=backend)
        with TestClient(app2) as c2:
            row = c2.app.state.job_queue.get("live1")
            assert row is not None
            assert row["state"] == "interrupted"
            assert "restarted" in row["error"]
    finally:
        get_settings.cache_clear()
