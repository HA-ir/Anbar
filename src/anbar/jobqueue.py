"""ARCH-02 (v0.15.24): durable in-process job queue.

Heavy operations (URL ingest, Telegram backup push, channel rebuild) must not
die with the process and must not silently vanish on restart. This module adds
a `jobs` table to the existing SQLite database and a small worker pool that
runs job coroutines with per-kind concurrency caps (§5.1 of the improvement
plan design):

- ingest_url  → max 2 concurrent (unchanged from the old `_SEM`)
- backup_now  → max 1
- channel_rebuild → max 1

Design points:
- **No new dependency**: jobs live in the same SQLite DB the server already
  writes (WAL, `busy_timeout` already configured).
- **Ordered fairness**: per-kind FIFO; the dispatcher never starves a kind.
- **Restart semantics**: rows found `running`/`queued` at boot flip to
  `interrupted` — the UI shows a clear state instead of the old 404 (companion
  to UX-03/ARCH-03). Automatic resume is out of scope by design (§5.1).
- **Pacing unchanged**: the queue only orders work; Telegram send pacing is
  still enforced by the storage layer (§5.1).
- **The old in-memory `JOBS` dict stays** as a live progress cache so the
  existing UI polling endpoint (`GET /upload/url/{id}`) keeps its exact
  response shape; DB rows are the durable source of truth.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable

log = logging.getLogger("anbar.jobqueue")

# per-kind concurrency caps (§5.1)
KIND_CONCURRENCY: dict[str, int] = {
    "ingest_url": 2,
    "backup_now": 1,
    "channel_rebuild": 1,
}

# finished rows are pruned after 1h (same rule as the old JOBS dict, ARCH-03)
JOB_TTL_S = 3600

Handler = Callable[[str, dict], Awaitable[None]]  # (job_id, payload) -> None


class JobQueue:
    """SQLite-backed job queue with a small asyncio worker pool."""

    def __init__(self, db, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self.db = db
        self._handlers: dict[str, Handler] = {}
        self._running: dict[str, int] = {kind: 0 for kind in KIND_CONCURRENCY}
        self._tasks: set[asyncio.Task] = set()
        self._stopped = False

    # ------------------------------------------------------------ schema/DML
    @staticmethod
    def _ensure_table(db) -> None:
        db._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
              id          TEXT PRIMARY KEY,
              kind        TEXT NOT NULL,
              payload     TEXT,
              state       TEXT NOT NULL DEFAULT 'queued',
              progress    INTEGER NOT NULL DEFAULT 0,
              total       INTEGER NOT NULL DEFAULT 0,
              error       TEXT,
              result      TEXT,
              created_at  INTEGER NOT NULL,
              started_at  INTEGER,
              finished_at INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state, created_at);
            """
        )
        db._conn.commit()

    def submit(
        self,
        kind: str,
        *,
        job_id: str,
        payload: dict | None = None,
        handler: Handler | None = None,
    ) -> str:
        """Register a job row and wake the dispatcher. Returns job_id."""
        if kind not in KIND_CONCURRENCY:
            raise ValueError(f"unknown job kind: {kind}")
        now = int(time.time())
        self.db._conn.execute(
            "INSERT OR REPLACE INTO jobs "
            "(id, kind, payload, state, created_at) VALUES (?, ?, ?, 'queued', ?)",
            (job_id, kind, json.dumps(payload or {}), now),
        )
        self.db._conn.commit()
        if handler is not None:
            self._handlers[kind] = handler
        self._wake(kind)
        return job_id

    # ------------------------------------------------------------- dispatch
    def _wake(self, kind: str) -> None:
        if self._stopped:
            return
        cap = KIND_CONCURRENCY[kind]
        while self._running[kind] < cap:
            row = self._next_queued(kind)
            if row is None:
                break
            job_id, payload_raw = row
            self._running[kind] += 1
            self.db._conn.execute(
                "UPDATE jobs SET state='running', started_at=? WHERE id=?",
                (int(time.time()), job_id),
            )
            self.db._conn.commit()
            task = asyncio.create_task(self._run_one(kind, job_id, payload_raw))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    def _next_queued(self, kind: str) -> tuple[str, str] | None:
        row = self.db._conn.execute(
            "SELECT id, payload FROM jobs WHERE kind=? AND state='queued' "
            "ORDER BY created_at, id LIMIT 1",
            (kind,),
        ).fetchone()
        return (row["id"], row["payload"]) if row else None

    async def _run_one(self, kind: str, job_id: str, payload_raw: str) -> None:
        try:
            payload = json.loads(payload_raw or "{}")
            handler = self._handlers.get(kind)
            if handler is None:
                raise RuntimeError(f"no handler registered for job kind {kind!r}")
            try:
                await handler(job_id, payload)
                # handler owns progress/state via set_progress/finish; if it
                # left the row running, close it out as done.
                row = self.get(job_id)
                if row and row["state"] == "running":
                    self.finish(job_id, result={"ok": True})
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("job %s (%s) failed: %s", job_id, kind, e)
                self.finish(job_id, error=str(e))
        except asyncio.CancelledError:
            # shutdown: leave an honest row behind instead of a phantom runner
            row = self.get(job_id)
            if row and row["state"] in ("queued", "running"):
                self.finish(job_id, error="server shutting down")
            raise
        except Exception as e:  # noqa: BLE001 — dispatcher-level failure
            log.warning("job %s (%s) dispatcher error: %s", job_id, kind, e)
            self.finish(job_id, error=str(e))
        finally:
            self._running[kind] -= 1
            self._wake(kind)

    # ------------------------------------------------------------ state API
    def set_progress(self, job_id: str, *, done: int, total: int) -> None:
        self.db._conn.execute(
            "UPDATE jobs SET progress=?, total=? WHERE id=?", (done, total, job_id)
        )
        self.db._conn.commit()

    def finish(self, job_id: str, *, result: dict | None = None, error: str | None = None) -> None:
        state = "error" if error else "done"
        self.db._conn.execute(
            "UPDATE jobs SET state=?, error=?, result=?, finished_at=? WHERE id=?",
            (
                state,
                error,
                json.dumps(result, ensure_ascii=False) if result is not None else None,
                int(time.time()),
                job_id,
            ),
        )
        self.db._conn.commit()

    def get(self, job_id: str) -> dict | None:
        row = self.db._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        out = dict(row)
        # parse result lazily for direct consumers (tests, job runners)
        if out.get("result"):
            try:
                out["result"] = json.loads(out["result"])
            except (json.JSONDecodeError, TypeError):
                pass
        return out

    def list(
        self, *, state: str | None = None, kind: str | None = None, limit: int = 50
    ) -> list[dict]:
        q = "SELECT * FROM jobs"
        conds, args = [], []
        if state:
            conds.append("state=?")
            args.append(state)
        if kind:
            conds.append("kind=?")
            args.append(kind)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY created_at DESC, id DESC LIMIT ?"
        args.append(max(1, min(int(limit), 200)))
        return [dict(r) for r in self.db._conn.execute(q, args).fetchall()]

    def cancel(self, job_id: str) -> bool:
        """Cancel a queued job (running jobs are cooperative — they keep running)."""
        row = self.get(job_id)
        if row and row["state"] == "queued":
            self.finish(job_id, error="cancelled")
            return True
        return False

    def delete(self, job_id: str) -> bool:
        row = self.get(job_id)
        if row and row["state"] in ("done", "error", "interrupted", "cancelled"):
            self.db._conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
            self.db._conn.commit()
            return True
        return False

    def prune(self) -> int:
        """Drop finished rows older than JOB_TTL_S (called from prune loop)."""
        cutoff = int(time.time()) - JOB_TTL_S
        cur = self.db._conn.execute(
            "DELETE FROM jobs WHERE state IN ('done','error','interrupted','cancelled') "
            "AND finished_at IS NOT NULL AND finished_at < ?",
            (cutoff,),
        )
        self.db._conn.commit()
        return cur.rowcount

    def mark_interrupted_on_boot(self) -> int:
        """Jobs found queued/running after a restart → interrupted (§5.1)."""
        cur = self.db._conn.execute(
            "UPDATE jobs SET state='interrupted', finished_at=?, "
            "error='server restarted while this job was in flight' "
            "WHERE state IN ('queued','running')",
            (int(time.time()),),
        )
        self.db._conn.commit()
        return cur.rowcount

    async def stop(self) -> None:
        self._stopped = True
        for t in list(self._tasks):
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
