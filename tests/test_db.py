"""F1: DB layer contract (WAL, objects CRUD, kv)."""
from __future__ import annotations

import time

from tglink.db import Database


def _obj(id: str, **kw) -> dict:
    base = {
        "id": id, "file_id": "fake-1", "backend": "fake",
        "filename": f"{id}.bin", "size": 123, "content_type": "application/octet-stream",
        "sha256": "0" * 64, "manifest": None, "uploader_key": None,
        "created_at": int(time.time()),
    }
    base.update(kw)
    return base


def test_insert_and_get(tmp_path):
    db = Database(tmp_path / "t.db")
    db.insert_object(_obj("a1"))
    row = db.get_object("a1")
    assert row is not None
    assert row["file_id"] == "fake-1"
    assert row["size"] == 123
    assert db.get_object("missing") is None
    db.close()


def test_list_ordering(tmp_path):
    db = Database(tmp_path / "t.db")
    now = int(time.time())
    db.insert_object(_obj("old", created_at=now - 100))
    db.insert_object(_obj("new", created_at=now))
    rows = db.list_objects()
    assert [r["id"] for r in rows] == ["new", "old"]
    db.close()


def test_delete(tmp_path):
    db = Database(tmp_path / "t.db")
    db.insert_object(_obj("x"))
    assert db.delete_object("x") is True
    assert db.delete_object("x") is False
    db.close()


def test_bump_downloads(tmp_path):
    db = Database(tmp_path / "t.db")
    db.insert_object(_obj("d"))
    db.bump_downloads("d")
    db.bump_downloads("d")
    row = db.get_object("d")
    assert row is not None
    assert row["downloaded"] == 2
    db.close()


def test_kv_roundtrip(tmp_path):
    db = Database(tmp_path / "t.db")
    assert db.kv_get("auth_state") is None
    assert db.kv_get("auth_state", "off") == "off"
    db.kv_set("auth_state", "on")
    db.kv_set("auth_state", "off")
    assert db.kv_get("auth_state") == "off"
    db.close()


def test_wal_mode(tmp_path):
    db = Database(tmp_path / "t.db")
    mode = db._conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    db.close()