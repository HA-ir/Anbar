"""SQLite metadata store (WAL mode). Metadata only — files never live here."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any


class _ObjectLRU:
    """Thread-safe fast in-memory LRU cache for hot metadata records."""

    def __init__(self, capacity: int = 4000):
        self.capacity = capacity
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def get(self, key: str) -> dict[str, Any] | None:
        if key not in self._cache:
            return None
        self._cache.move_to_end(key)
        return dict(self._cache[key])

    def put(self, key: str, value: dict[str, Any]) -> None:
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = dict(value)
        if len(self._cache) > self.capacity:
            self._cache.popitem(last=False)

    def invalidate(self, key: str) -> None:
        self._cache.pop(key, None)

    def clear(self) -> None:
        self._cache.clear()


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
CREATE INDEX IF NOT EXISTS idx_objects_deleted ON objects(deleted_at);
CREATE INDEX IF NOT EXISTS idx_objects_filename ON objects(filename);
CREATE TABLE IF NOT EXISTS kv (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rate (
  k TEXT PRIMARY KEY,
  window_start INTEGER NOT NULL,
  n INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS audit_logs (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at   INTEGER NOT NULL,
  event        TEXT NOT NULL,
  actor        TEXT NOT NULL,
  target       TEXT,
  ip           TEXT,
  details      TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);
"""


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA mmap_size=268435456")
    conn.execute("PRAGMA cache_size=-64000")
    conn.execute("PRAGMA temp_store=MEMORY")
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
        self._obj_cache = _ObjectLRU()

    def _migrate(self) -> None:
        """Add columns introduced after v0.9 (idempotent, ALTER-only)."""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(objects)")}
        if "deleted_at" not in cols:
            self._conn.execute("ALTER TABLE objects ADD COLUMN deleted_at INTEGER")
            self._conn.commit()

    # -- objects ---------------------------------------------------------
    def insert_object(self, obj: dict[str, Any]) -> None:
        created_at = obj.get("created_at", int(time.time()))
        downloaded = obj.get("downloaded", 0)
        self._conn.execute(
            """INSERT INTO objects
               (id, file_id, backend, filename, size, content_type, sha256,
                manifest, uploader_key, created_at, downloaded)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                created_at,
                downloaded,
            ),
        )
        self._conn.commit()
        full_obj = {
            "id": obj["id"],
            "file_id": obj["file_id"],
            "backend": obj["backend"],
            "filename": obj["filename"],
            "size": obj["size"],
            "content_type": obj.get("content_type"),
            "sha256": obj.get("sha256"),
            "manifest": obj.get("manifest"),
            "uploader_key": obj.get("uploader_key"),
            "created_at": created_at,
            "downloaded": downloaded,
            "deleted_at": None,
        }
        self._obj_cache.put(obj["id"], full_obj)

    def get_object(self, obj_id: str, *, include_trashed: bool = False) -> dict[str, Any] | None:
        if not include_trashed:
            cached = self._obj_cache.get(obj_id)
            if cached is not None and not cached.get("deleted_at"):
                return cached
        row = self._conn.execute("SELECT * FROM objects WHERE id = ?", (obj_id,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        if not include_trashed and d.get("deleted_at"):
            return None  # soft-deleted rows vanish from the normal path
        if not d.get("deleted_at"):
            self._obj_cache.put(obj_id, d)
        return d

    def list_objects(
        self, limit: int = 50, offset: int = 0, trash: bool = False
    ) -> list[dict[str, Any]]:
        where = "WHERE deleted_at IS NOT NULL" if trash else "WHERE deleted_at IS NULL"
        order = "deleted_at DESC" if trash else "created_at DESC"
        rows = self._conn.execute(
            f"SELECT id, filename, size, backend, created_at, downloaded, deleted_at, manifest, content_type "
            f"FROM objects {where} ORDER BY {order} LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            chunk_count = 1
            if d.get("manifest"):
                try:
                    m = json.loads(d["manifest"])
                    chunk_count = len(m.get("chunks", [])) or 1
                except Exception:
                    chunk_count = 1
            d["chunks"] = chunk_count
            d.pop("manifest", None)
            out.append(d)
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
        self._obj_cache.invalidate(obj_id)
        cur = self._conn.execute("DELETE FROM objects WHERE id = ?", (obj_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def list_objects_by_prefix(
        self, prefix: str, *, include_trashed: bool = False
    ) -> list[dict[str, Any]]:
        """List all objects starting with a prefix (for folder operations)."""
        where = (
            "WHERE filename LIKE ? AND deleted_at IS NULL"
            if not include_trashed
            else "WHERE filename LIKE ?"
        )
        rows = self._conn.execute(
            f"SELECT * FROM objects {where} ORDER BY created_at DESC",
            (f"{prefix}%",),
        ).fetchall()
        return [dict(r) for r in rows]

    def rename_folder(self, old_prefix: str, new_prefix: str) -> int:
        """Rename/move all files under old_prefix to new_prefix."""
        self._obj_cache.clear()
        old_prefix = old_prefix.rstrip("/") + "/"
        new_prefix = new_prefix.rstrip("/") + "/"
        rows = self._conn.execute(
            "SELECT id, filename FROM objects WHERE filename LIKE ? AND deleted_at IS NULL",
            (f"{old_prefix}%",),
        ).fetchall()
        count = 0
        for r in rows:
            old_name = r["filename"]
            suffix = old_name[len(old_prefix):]
            new_name = new_prefix + suffix
            self._conn.execute("UPDATE objects SET filename = ? WHERE id = ?", (new_name, r["id"]))
            count += 1
        self._conn.commit()
        return count

    def copy_folder(self, src_prefix: str, dst_prefix: str) -> int:
        """Duplicate metadata of all files under src_prefix to dst_prefix."""
        import uuid
        src_prefix = src_prefix.rstrip("/") + "/"
        dst_prefix = dst_prefix.rstrip("/") + "/"
        rows = self._conn.execute(
            "SELECT * FROM objects WHERE filename LIKE ? AND deleted_at IS NULL",
            (f"{src_prefix}%",),
        ).fetchall()
        count = 0
        now = int(time.time())
        for r in rows:
            d = dict(r)
            suffix = d["filename"][len(src_prefix):]
            new_name = dst_prefix + suffix
            new_id = uuid.uuid4().hex[:12]
            self._conn.execute(
                """INSERT INTO objects
                   (id, file_id, backend, filename, size, content_type, sha256,
                    manifest, uploader_key, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    new_id,
                    d["file_id"],
                    d["backend"],
                    new_name,
                    d["size"],
                    d.get("content_type"),
                    d.get("sha256"),
                    d.get("manifest"),
                    d.get("uploader_key"),
                    now,
                ),
            )
            count += 1
        self._conn.commit()
        return count

    def copy_object(self, obj_id: str, new_filename: str | None = None) -> dict[str, Any] | None:
        """Duplicate an object's metadata pointing to the same storage chunks with a new ID."""
        row = self._conn.execute(
            "SELECT * FROM objects WHERE id = ? AND deleted_at IS NULL",
            (obj_id,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        import uuid

        new_id = uuid.uuid4().hex[:12]
        if not new_filename:
            fn = d["filename"]
            if "." in fn and not fn.startswith("."):
                base, ext = fn.rsplit(".", 1)
                new_filename = f"{base} (copy).{ext}"
            else:
                new_filename = f"{fn} (copy)"

        now = int(time.time())
        self._conn.execute(
            """INSERT INTO objects
               (id, file_id, backend, filename, size, content_type, sha256,
                manifest, uploader_key, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_id,
                d["file_id"],
                d["backend"],
                new_filename,
                d["size"],
                d.get("content_type"),
                d.get("sha256"),
                d.get("manifest"),
                d.get("uploader_key"),
                now,
            ),
        )
        self._conn.commit()
        return {
            "id": new_id,
            "filename": new_filename,
            "size": d["size"],
            "created_at": now,
        }

    def soft_delete_folder(self, prefix: str) -> int:
        """Soft-delete all files under a prefix."""
        self._obj_cache.clear()
        prefix = prefix.rstrip("/") + "/"
        now = int(time.time())
        cur = self._conn.execute(
            "UPDATE objects SET deleted_at = ? "
            "WHERE (filename LIKE ? OR filename = ?) AND deleted_at IS NULL",
            (now, f"{prefix}%", prefix.rstrip("/")),
        )
        self._conn.commit()
        return cur.rowcount

    # -- trash (v0.10): soft delete → restore / hard purge -----------------
    def soft_delete(self, obj_id: str) -> bool:
        self._obj_cache.invalidate(obj_id)
        cur = self._conn.execute(
            "UPDATE objects SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
            (int(time.time()), obj_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def restore_object(self, obj_id: str) -> bool:
        self._obj_cache.invalidate(obj_id)
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
        self._obj_cache.clear()
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
        self._obj_cache.invalidate(obj_id)
        cur = self._conn.execute("UPDATE objects SET filename = ? WHERE id = ?", (filename, obj_id))
        self._conn.commit()
        return cur.rowcount > 0

    def move_objects_to_prefix(self, ids: list[str], new_prefix: str) -> dict[str, Any]:
        """Move objects into a folder (prefix). Only the path portion of the
        filename changes; the basename is preserved. Collisions are skipped,
        not overwritten. Returns {"moved": int, "skipped": [{id, reason}]}.
        """
        self._obj_cache.clear()
        if not ids:
            return {"moved": 0, "skipped": []}
        prefix = (new_prefix or "").strip("/")
        prefix = prefix + "/" if prefix else ""
        ph = ",".join("?" for _ in ids)
        rows = self._conn.execute(
            f"SELECT id, filename FROM objects WHERE id IN ({ph}) AND deleted_at IS NULL",
            tuple(ids),
        ).fetchall()
        moved = 0
        skipped: list[dict[str, Any]] = []
        for r in rows:
            obj_id = r["id"]
            old_name = r["filename"]
            base = old_name.rsplit("/", 1)[-1]
            if not base:
                skipped.append({"id": obj_id, "reason": "no-basename"})
                continue
            new_name = prefix + base
            if new_name == old_name:
                moved += 1  # already at the destination
                continue
            clash = self._conn.execute(
                "SELECT 1 FROM objects WHERE filename = ? AND id != ? AND deleted_at IS NULL",
                (new_name, obj_id),
            ).fetchone()
            if clash:
                skipped.append({"id": obj_id, "reason": "exists", "name": new_name})
                continue
            self._conn.execute("UPDATE objects SET filename = ? WHERE id = ?", (new_name, obj_id))
            moved += 1
        self._conn.commit()
        return {"moved": moved, "skipped": skipped}

    def bump_downloads(self, obj_id: str) -> None:
        self._conn.execute("UPDATE objects SET downloaded = downloaded + 1 WHERE id = ?", (obj_id,))
        self._conn.commit()
        cached = self._obj_cache.get(obj_id)
        if cached is not None:
            cached["downloaded"] = cached.get("downloaded", 0) + 1
            self._obj_cache.put(obj_id, cached)

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

    def kv_prune_prefix(self, prefix: str, max_age_s: int) -> int:
        """Delete kv rows whose key starts with `prefix` and whose stored
        JSON payload is older than `max_age_s` (epoch seconds embedded at
        write time is NOT available, so we use a sentinel: rows are written
        with the current epoch appended in a JSON envelope `{"ts": ...}`).

        Resume checkpoints (`upres:<id>`) store a JSON list of chunks — no
        timestamp. To keep this generic without changing the stored format,
        we prune by matching a `"_ts"` field when present; rows without it
        are pruned when older than max_age_s based on rowid order (best
        effort). Returns rows removed.
        """
        cutoff = int(time.time()) - max_age_s
        rows = self._conn.execute(
            "SELECT k, v FROM kv WHERE k LIKE ?", (prefix + "%",)
        ).fetchall()
        removed = 0
        for r in rows:
            try:
                payload = json.loads(r["v"])
            except (json.JSONDecodeError, TypeError):
                continue
            ts = payload.get("_ts") if isinstance(payload, dict) else None
            if ts is None:
                continue
            if int(ts) < cutoff:
                self._conn.execute("DELETE FROM kv WHERE k = ?", (r["k"],))
                removed += 1
        self._conn.commit()
        return removed

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

    def backup_bytes(self) -> bytes:
        """Create a consistent, point-in-time binary snapshot of the SQLite WAL database."""
        mem_conn = sqlite3.connect(":memory:")
        self._conn.backup(mem_conn)
        data = mem_conn.serialize()
        mem_conn.close()
        return data

    def restore_bytes(self, data: bytes) -> dict:
        """Restore database from a binary SQLite backup snapshot atomically."""
        if not data.startswith(b"SQLite format 3\x00"):
            raise ValueError("Invalid backup file: header is not a valid SQLite database.")

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            tf.write(data)
            tmp_path = tf.name

        try:
            src_conn = sqlite3.connect(tmp_path)
            check = src_conn.execute("PRAGMA integrity_check").fetchone()
            if not check or check[0] != "ok":
                raise ValueError(f"Corrupted backup database: {check}")

            tables = {
                row[0]
                for row in src_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            required = {"objects", "kv"}
            if not required.issubset(tables):
                raise ValueError(f"Missing required tables in backup: {required - tables}")

            n_objs = src_conn.execute("SELECT count(*) FROM objects").fetchone()[0]

            # Atomic copy to active live database
            src_conn.backup(self._conn)
            src_conn.close()
            self._obj_cache.clear()

            # Re-apply WAL & performance pragmas
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA mmap_size=268435456")
            self._conn.execute("PRAGMA cache_size=-64000")
            self._conn.execute("PRAGMA temp_store=MEMORY")
            return {
                "restored": True,
                "objects_count": n_objs,
            }
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def restore_from_file(self, path: str) -> dict:
        """Restore database from a SQLite backup file on disk (no RAM copy).

        SEC-05 (v0.15.20): same validation contract as `restore_bytes`,
        but reads from a streamed temp file — used by the backup import
        endpoint so multi-hundred-MB backups never buffer in memory.
        """
        with open(path, "rb") as f:
            header = f.read(16)
        if header != b"SQLite format 3\x00":
            raise ValueError("Invalid backup file: header is not a valid SQLite database.")

        src_conn = sqlite3.connect(path)
        try:
            check = src_conn.execute("PRAGMA integrity_check").fetchone()
            if not check or check[0] != "ok":
                raise ValueError(f"Corrupted backup database: {check}")

            tables = {
                row[0]
                for row in src_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            required = {"objects", "kv"}
            if not required.issubset(tables):
                raise ValueError(f"Missing required tables in backup: {required - tables}")

            n_objs = src_conn.execute("SELECT count(*) FROM objects").fetchone()[0]

            # Atomic copy to active live database
            src_conn.backup(self._conn)
            self._obj_cache.clear()

            # Re-apply WAL & performance pragmas
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA mmap_size=268435456")
            self._conn.execute("PRAGMA cache_size=-64000")
            self._conn.execute("PRAGMA temp_store=MEMORY")
            return {
                "restored": True,
                "objects_count": n_objs,
            }
        finally:
            src_conn.close()

    def log_audit(
        self,
        event: str,
        actor: str = "admin",
        target: str | None = None,
        ip: str | None = None,
        details: dict | str | None = None,
    ) -> int:
        """Record an audit trail event."""
        det_str = (
            json.dumps(details, ensure_ascii=False)
            if isinstance(details, (dict, list))
            else (str(details) if details else None)
        )
        cur = self._conn.execute(
            """
            INSERT INTO audit_logs (created_at, event, actor, target, ip, details)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (int(time.time()), event, actor, target, ip, det_str),
        )
        self._conn.commit()
        return cur.lastrowid

    def audit_prune(self, max_age_s: int = 90 * 86400) -> int:
        """Delete audit records older than `max_age_s` (default 90 days).

        ARCH-04 (v0.15.20): audit_logs grew unboundedly; called from the
        periodic prune loop in main.py. Returns rows removed.
        """
        cur = self._conn.execute(
            "DELETE FROM audit_logs WHERE created_at < ?",
            (int(time.time()) - max_age_s,),
        )
        self._conn.commit()
        return cur.rowcount

    def list_audit_logs(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """List audit logs ordered by newest first."""
        cur = self._conn.execute(
            """
            SELECT id, created_at, event, actor, target, ip, details
            FROM audit_logs
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (max(1, min(limit, 200)), max(0, offset)),
        )
        out = []
        for r in cur.fetchall():
            d = dict(r)
            if d.get("details"):
                try:
                    d["details"] = json.loads(d["details"])
                except Exception:
                    pass
            out.append(d)
        return out

    def close(self) -> None:
        self._conn.close()
