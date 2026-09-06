"""Durable job storage synchronized through the shared SQLite lock."""

from __future__ import annotations

import contextlib
import json
import sqlite3
import time
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


class JobStore:
    def __init__(self, db: Any) -> None:
        self.db = db
        self._conn = db.connection() if hasattr(db, "connection") else db._conn

    def _run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        lock = getattr(self.db, "lock", None)
        with lock() if lock is not None else contextlib.nullcontext():
            result = fn(self._conn)
            self._conn.commit()
            return result

    def ensure_table(self) -> None:
        def run(conn: sqlite3.Connection) -> None:
            conn.executescript(
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

        self._run(run)

    def submit(self, job_id: str, kind: str, payload: dict[str, Any]) -> None:
        def run(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT OR REPLACE INTO jobs "
                "(id, kind, payload, state, created_at) VALUES (?, ?, ?, 'queued', ?)",
                (job_id, kind, json.dumps(payload), int(time.time())),
            )

        self._run(run)

    def next_queued(self, kind: str) -> tuple[str, str] | None:
        def run(conn: sqlite3.Connection) -> tuple[str, str] | None:
            row = conn.execute(
                "SELECT id, payload FROM jobs WHERE kind=? AND state='queued' "
                "ORDER BY created_at, id LIMIT 1",
                (kind,),
            ).fetchone()
            return (row["id"], row["payload"]) if row else None

        return self._run(run)

    def mark_running(self, job_id: str) -> None:
        def run(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE jobs SET state='running', started_at=? WHERE id=?",
                (int(time.time()), job_id),
            )

        self._run(run)

    def update_progress(self, job_id: str, done: int, total: int) -> None:
        def run(conn: sqlite3.Connection) -> None:
            conn.execute("UPDATE jobs SET progress=?, total=? WHERE id=?", (done, total, job_id))

        self._run(run)

    def set_progress(self, job_id: str, done: int, total: int) -> None:
        self.update_progress(job_id, done, total)

    def finish(
        self, job_id: str, state: str, result: dict[str, Any] | None, error: str | None
    ) -> None:
        def run(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE jobs SET state=?, error=?, result=?, finished_at=? WHERE id=?",
                (
                    state,
                    error,
                    json.dumps(result, ensure_ascii=False) if result is not None else None,
                    int(time.time()),
                    job_id,
                ),
            )

        self._run(run)

    def get(self, job_id: str) -> dict[str, Any] | None:
        def run(conn: sqlite3.Connection) -> dict[str, Any] | None:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                return None
            out = dict(row)
            if out.get("result"):
                try:
                    out["result"] = json.loads(out["result"])
                except (json.JSONDecodeError, TypeError):
                    pass
            return out

        return self._run(run)

    def list(self, state: str | None, kind: str | None, limit: int) -> list[dict[str, Any]]:
        query = "SELECT * FROM jobs"
        conditions = []
        params: list[object] = []
        if state:
            conditions.append("state=?")
            params.append(state)
        if kind:
            conditions.append("kind=?")
            params.append(kind)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 200)))

        def run(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            return [dict(row) for row in conn.execute(query, params).fetchall()]

        return self._run(run)

    def delete(self, job_id: str) -> int:
        def run(conn: sqlite3.Connection) -> int:
            return int(conn.execute("DELETE FROM jobs WHERE id=?", (job_id,)).rowcount)

        return self._run(run)

    def prune(self, cutoff: int) -> int:
        def run(conn: sqlite3.Connection) -> int:
            return int(
                conn.execute(
                    "DELETE FROM jobs WHERE state IN ('done','error','interrupted','cancelled') "
                    "AND finished_at IS NOT NULL AND finished_at < ?",
                    (cutoff,),
                ).rowcount
            )

        return self._run(run)

    def mark_interrupted_on_boot(self) -> int:
        def run(conn: sqlite3.Connection) -> int:
            return int(
                conn.execute(
                    "UPDATE jobs SET state='interrupted', finished_at=?, "
                    "error='server restarted while this job was in flight' "
                    "WHERE state IN ('queued','running')",
                    (int(time.time()),),
                ).rowcount
            )

        return self._run(run)

    def stats(self) -> dict[str, int]:
        def run(conn: sqlite3.Connection) -> dict[str, int]:
            rows = conn.execute("SELECT state, COUNT(*) as cnt FROM jobs GROUP BY state").fetchall()
            return {r["state"]: int(r["cnt"]) for r in rows}

        return self._run(run)
