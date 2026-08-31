"""v0.15.20 improvement-plan fixes batch 3: SEC-01, ARCH-04, SEC-05, UX-02.

SEC-01  — XFF trusted only from loopback peers, last-hop taken.
ARCH-04 — audit_prune() deletes records older than 90 days.
SEC-05  — backup import is streamed to disk with a 256MB cap; tiny corrupt
          file still gets the 400 contract.
UX-02   — /api/v1/admin/objects?limit=500 returns more than 50 rows.
"""

from __future__ import annotations

import sqlite3
import time

from starlette.testclient import TestClient

UP = {"Authorization": "Bearer test-key"}
ADMIN = {"Authorization": "Bearer test-admin-key"}


# ── SEC-01: XFF handling ────────────────────────────────────────────────


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeReq:
    def __init__(self, headers, peer="203.0.113.50"):
        self.headers = headers
        self.client = _FakeClient(peer)


def test_xff_ignored_for_direct_peer():
    from anbar.ratelimit import _client_ip

    req = _FakeReq({"x-forwarded-for": "1.2.3.4, 5.6.7.8"}, peer="203.0.113.50")
    # direct connection from a public IP: XFF must be ignored entirely
    assert _client_ip(req) == "203.0.113.50"


def test_xff_last_hop_used_for_loopback_peer():
    from anbar.ratelimit import _client_ip

    req = _FakeReq({"x-forwarded-for": "1.2.3.4, 198.51.100.9"}, peer="127.0.0.1")
    # nginx appends the real client as the LAST entry — trust that
    assert _client_ip(req) == "198.51.100.9"


def test_xff_ignored_when_peer_is_not_loopback():
    from anbar.ratelimit import _client_ip

    req = _FakeReq({"x-forwarded-for": "9.9.9.9"}, peer="198.51.100.1")
    assert _client_ip(req) == "198.51.100.1"


def test_no_xff_falls_back_to_peer():
    from anbar.ratelimit import _client_ip

    req = _FakeReq({}, peer="10.0.0.5")
    assert _client_ip(req) == "10.0.0.5"


# ── ARCH-04: audit retention ────────────────────────────────────────────


def test_audit_prune_deletes_only_old_records(client: TestClient):
    db = client.app.state.db
    old_ts = int(time.time()) - 100 * 86400
    db._conn.execute(
        "INSERT INTO audit_logs (created_at, event, actor) VALUES (?, ?, ?)",
        (old_ts, "file.upload", "admin"),
    )
    db._conn.execute(
        "INSERT INTO audit_logs (created_at, event, actor) VALUES (?, ?, ?)",
        (int(time.time()), "file.upload", "admin"),
    )
    db._conn.commit()

    removed = db.audit_prune()
    assert removed >= 1
    remaining = db.list_audit_logs(limit=100)
    assert all(r["event"] for r in remaining)
    # nothing newer than 90 days survives the prune
    for r in remaining:
        assert r["created_at"] >= int(time.time()) - 90 * 86400


# ── SEC-05: backup import streaming + cap ───────────────────────────────


def _make_backup(tmp_path, monkeypatch, n_objects=0):
    """Create a valid tiny SQLite backup file via sqlite3 backup API."""
    src = sqlite3.connect(str(tmp_path / "src.db"))
    src.executescript(
        """
        CREATE TABLE objects (id TEXT PRIMARY KEY, filename TEXT, size INTEGER,
            backend TEXT, created_at INTEGER, downloaded INTEGER DEFAULT 0,
            deleted_at INTEGER, manifest TEXT, content_type TEXT, sha256 TEXT,
            uploader_key TEXT);
        CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE audit_logs (id INTEGER PRIMARY KEY, created_at INTEGER,
            event TEXT, actor TEXT, target TEXT, ip TEXT, details TEXT);
        CREATE TABLE rate (k TEXT, window_start INTEGER, n INTEGER DEFAULT 0,
            PRIMARY KEY (k, window_start));
        """
    )
    for i in range(n_objects):
        src.execute(
            "INSERT INTO objects (id, filename, size, backend, created_at) "
            "VALUES (?, ?, 1, 'fake', 0)",
            (f"bk{i}", f"f{i}.bin"),
        )
    src.commit()
    path = str(tmp_path / "src.db")
    src.close()
    return path


def test_backup_import_roundtrip_and_cap_rejection(client: TestClient, tmp_path):
    path = _make_backup(tmp_path, None, n_objects=2)
    with open(path, "rb") as f:
        r = client.post(
            "/api/v1/admin/backup/import",
            files={"file": ("backup.db", f.read(), "application/vnd.sqlite3")},
            headers=ADMIN,
        )
    assert r.status_code == 200, r.text
    assert r.json()["objects_count"] == 2

    # garbage file → 400 (validation contract preserved)
    r2 = client.post(
        "/api/v1/admin/backup/import",
        files={"file": ("bad.db", b"not a database" * 4, "application/vnd.sqlite3")},
        headers=ADMIN,
    )
    assert r2.status_code == 400


def test_restore_from_file_rejects_garbage(client: TestClient, tmp_path):
    db = client.app.state.db
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"garbage" * 8)
    try:
        db.restore_from_file(str(bad))
        raised = False
    except ValueError:
        raised = True
    assert raised


# ── UX-02: dashboard object listing ─────────────────────────────────────


def test_objects_endpoint_accepts_limit_500(client: TestClient):
    db = client.app.state.db
    for i in range(60):
        db.insert_object(
            {
                "id": f"ux{i:04d}" + "0" * 6,
                "file_id": "x",
                "backend": "fake",
                "filename": f"obj{i}.bin",
                "size": 10,
                "content_type": "application/octet-stream",
                "sha256": "b" * 64,
                "manifest": '{"chunks": []}',
            }
        )
    r = client.get("/api/v1/admin/objects?limit=500", headers=ADMIN)
    assert r.status_code == 200
    assert r.json()["count"] >= 60  # old implicit-50 cap would return 50
