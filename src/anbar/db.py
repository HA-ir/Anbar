"""SQLite metadata store (WAL mode). Metadata only — files never live here."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS objects (
  id            TEXT PRIMARY KEY,
  file_id       TEXT NOT NULL,
  backend       TEXT NOT NULL,
  filename      TEXT NOT NULL,
  size          INTEGER NOT NULL,
  content_type  TEXT,
  sha256        TEXT,
  manifest      TEXT,
  uploader_key  TEXT,
  created_at    INTEGER NOT NULL,
  downloaded    INTEGER DEFAULT 0,
  deleted_at    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_objects_created ON objects(created_at DESC);
CREATE TABLE IF NOT EXISTS kv (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rate (
  k TEXT PRIMARY KEY,
  window_start INTEGER NOT NULL,
  n INTEGER NOT NULL DEFAULT 0
);
"""


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


class Database:
    # trash retention: soft-deleted rows purge themselves after 7 days
    TRASH_TTL_S = 7 * 86400

    def __init__(self, path: Path):
        self.path = path
        self._conn = _connect(path)
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after v0.9 (idempotent, ALTER-only)."""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(objects)")}
        if "deleted_at" not in cols:
            self._conn.execute("ALTER TABLE objects ADD COLUMN deleted_at INTEGER")
            self._conn.commit()

    # -- objects ---------------------------------------------------------
    def insert_object(self, obj: dict[str, Any]) -> None:
        self._conn.execute(
            """INSERT INTO objects
               (id, file_id, backend, filename, size, content_type, sha256,
                manifest, uploader_key, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                obj["id"],
                obj["file_id"],
                obj["backend"],
                obj["filename"],
                obj["size"],
                obj.get("content_type"),
                obj.get("sha256"),
                obj.get("manifest"),
                obj.get("uploader_key"),
                obj.get("created_at", int(time.time())),
            ),
        )
        self._conn.commit()

    def get_object(self, obj_id: str, *, include_trashed: bool = False) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM objects WHERE id = ?", (obj_id,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        if not include_trashed and d.get("deleted_at"):
            return None  # soft-deleted rows vanish from the normal path
        return d

    def list_objects(
        self, limit: int = 50, offset: int = 0, trash: bool = False
    ) -> list[dict[str, Any]]:
        where = "WHERE deleted_at IS NOT NULL" if trash else "WHERE deleted_at IS NULL"
        order = "deleted_at DESC" if trash else "created_at DESC"
        rows = self._conn.execute(
            f"SELECT id, filename, size, backend, created_at, downloaded, deleted_at "
            f"FROM objects {where} ORDER BY {order} LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        out = [{**dict(r), "chunks": 0} for r in rows]
        return out

    def list_objects_full(self, limit: int = 500, trash: bool = False) -> list[dict[str, Any]]:
        """Listing that includes manifests (needed for ZIP/purge work)."""
        where = "WHERE deleted_at IS NOT NULL" if trash else "WHERE deleted_at IS NULL"
        rows = self._conn.execute(
            f"SELECT * FROM objects {where} ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["chunks"] = len(json.loads(d["manifest"])["chunks"]) if d.get("manifest") else 0
            except (json.JSONDecodeError, KeyError, TypeError):
                d["chunks"] = 0
            return_list = [
                "id",
                "filename",
                "size",
                "backend",
                "created_at",
                "downloaded",
                "chunks",
                "content_type",
                "manifest",
                "uploader_key",
                "file_id",
                "deleted_at",
            ]
            out.append({k: d[k] for k in return_list if k in d})
        return out

    def delete_object(self, obj_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM objects WHERE id = ?", (obj_id,))
        self._conn.commit()
        return cur.rowcount > 0

    # -- trash (v0.10): soft delete → restore / hard purge -----------------
    def soft_delete(self, obj_id: str) -> bool:
        cur = self._conn.execute(
            "UPDATE objects SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
            (int(time.time()), obj_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def restore_object(self, obj_id: str) -> bool:
        cur = self._conn.execute(
            "UPDATE objects SET deleted_at = NULL WHERE id = ? AND deleted_at IS NOT NULL",
            (obj_id,),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def trash_count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM objects WHERE deleted_at IS NOT NULL"
        ).fetchone()
        return row["n"]

    def purge_expired_trash(self) -> list[str]:
        """Hard-delete rows whose soft-delete is older than TRASH_TTL_S.

        Only unsets metadata — the caller is responsible for deleting the
        Telegram blobs before (or after) dropping the row. Returns the ids
        purged so the API layer can clean remote blobs.
        """
        cutoff = int(time.time()) - self.TRASH_TTL_S
        rows = self._conn.execute(
            "SELECT id FROM objects WHERE deleted_at IS NOT NULL AND deleted_at < ?",
            (cutoff,),
        ).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            self._conn.executemany("DELETE FROM objects WHERE id = ?", [(i,) for i in ids])
            self._conn.commit()
        return ids

    def rename_object(self, obj_id: str, filename: str) -> bool:
        cur = self._conn.execute("UPDATE objects SET filename = ? WHERE id = ?", (filename, obj_id))
        self._conn.commit()
        return cur.rowcount > 0

    def bump_downloads(self, obj_id: str) -> None:
        self._conn.execute("UPDATE objects SET downloaded = downloaded + 1 WHERE id = ?", (obj_id,))
        self._conn.commit()

    # -- kv (toggles, stats) ---------------------------------------------
    def kv_get(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT v FROM kv WHERE k = ?", (key,)).fetchone()
        return row["v"] if row else default

    def kv_set(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO kv (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
            (key, value),
        )
        self._conn.commit()

    def kv_delete(self, key: str) -> None:
        self._conn.execute("DELETE FROM kv WHERE k = ?", (key,))
        self._conn.commit()

    def kv_all(self) -> list[tuple[str, str]]:
        """All kv pairs (small table; used for slug cleanup on delete)."""
        rows = self._conn.execute("SELECT k, v FROM kv").fetchall()
        return [(r["k"], r["v"]) for r in rows]

    # -- rate limiting (fixed windows in SQLite) ------------------------------
    def rate_check(self, key: str, window_s: int, limit: int) -> tuple[bool, int, int]:
        """Atomically check+count one request in a fixed window.

        Returns (allowed, retry_after_s, current_count). Rows from
        finished windows are recycled in place.
        """
        now = int(time.time())
        win_start = now - (now % window_s)
        self._conn.execute(
            """INSERT INTO rate (k, window_start, n) VALUES (?, ?, 1)
               ON CONFLICT(k) DO UPDATE SET
                 window_start = CASE WHEN rate.window_start = ? THEN ? ELSE ? END,
                 n = CASE
                       WHEN rate.window_start = ? THEN rate.n + 1
                       ELSE 1
                     END""",
            (key, win_start, win_start, win_start, now, win_start),
        )
        self._conn.commit()
        row = self._conn.execute("SELECT window_start, n FROM rate WHERE k = ?", (key,)).fetchone()
        n = row["n"] if row else 1
        if row is not None and row["window_start"] < win_start:  # pragma: no cover
            n = 1
        if n > limit:
            retry_after = win_start + window_s - now
            return False, max(1, retry_after), n
        return True, 0, n

    def rate_prune(self, max_age_s: int = 3600) -> int:
        """Drop finished windows; returns rows removed."""
        cur = self._conn.execute(
            "DELETE FROM rate WHERE window_start < ?",
            (int(time.time()) - max_age_s,),
        )
        self._conn.commit()
        return cur.rowcount

    # -- maintenance ------------------------------------------------------
    def vacuum(self) -> None:
        self._conn.execute("VACUUM")

    def close(self) -> None:
        self._conn.close()
