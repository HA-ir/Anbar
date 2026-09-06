"""Tests for Wave 3 (Decomposition, Links Table, Templates) and Wave 4 (Metrics, Deep Health)."""

from __future__ import annotations

import io
import time

from fastapi.testclient import TestClient

ADMIN = {"Authorization": "Bearer test-admin-key"}


def test_links_table_crud(tmp_path):
    from anbar.db import Database

    db = Database(tmp_path / "crud.db")
    """Verify dedicated links table CRUD and lifecycle operations."""
    now = int(time.time())
    exp = now + 3600
    db.link_insert(
        obj_id="obj-test-1",
        exp=exp,
        sig="test-sig",
        slug="test-slug",
        pw=True,
        max_dl=5,
        created_at=now,
        downloads=1,
    )

    # 1. Get
    row = db.link_get("obj-test-1", exp)
    assert row is not None
    assert row["obj_id"] == "obj-test-1"
    assert row["exp"] == exp
    assert row["sig"] == "test-sig"
    assert row["slug"] == "test-slug"
    assert row["pw"] == 1
    assert row["max_dl"] == 5
    assert row["downloads"] == 1
    assert row["revoked"] == 0

    # 2. Check revocation
    assert db.link_is_revoked("obj-test-1", exp) is False

    # 3. Bump downloads
    db.link_bump_downloads("obj-test-1")
    row_after = db.link_get("obj-test-1", exp)
    assert row_after is not None
    assert row_after["downloads"] == 2

    # 4. Live links listing
    live = db.link_list(limit=10, include_dead=False)
    assert any(r["obj_id"] == "obj-test-1" for r in live)

    # 5. Revoke
    assert db.link_revoke("obj-test-1", exp) is True
    assert db.link_is_revoked("obj-test-1", exp) is True

    # Revoking already-revoked link returns False
    assert db.link_revoke("obj-test-1", exp) is False

    # 6. Dead links hidden in normal list, present in include_dead
    assert not any(r["obj_id"] == "obj-test-1" for r in db.link_list(limit=10, include_dead=False))
    assert any(r["obj_id"] == "obj-test-1" for r in db.link_list(limit=10, include_dead=True))


def test_links_migration_from_kv(tmp_path):
    """Verify pre-existing kv link entries migrate cleanly to links table."""
    import json
    import sqlite3

    from anbar.db import SCHEMA, Database

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    # Insert legacy kv link without links table entry
    now = int(time.time())
    meta = {
        "sig": "legacy-sig",
        "slug": "legacy-slug",
        "pw": False,
        "max_dl": 10,
        "created_at": now,
        "downloads": 3,
    }
    conn.execute(
        "INSERT INTO kv (k, v) VALUES (?, ?)", (f"link:legacy-obj:{now + 600}", json.dumps(meta))
    )
    conn.commit()
    conn.close()

    # Opening Database triggers _migrate which should populate links
    db = Database(db_path)
    row = db.link_get("legacy-obj", now + 600)
    assert row is not None
    assert row["slug"] == "legacy-slug"
    assert row["downloads"] == 3
    assert row["max_dl"] == 10


def test_kv_prefix_query(tmp_path):
    from anbar.db import Database

    db = Database(tmp_path / "prefix.db")
    """Verify kv_prefix returns only matching rows."""
    db.kv_set("album:tok1", "val1")
    db.kv_set("album:tok2", "val2")
    db.kv_set("other:key", "val3")

    results = dict(db.kv_prefix("album:"))
    assert "album:tok1" in results
    assert "album:tok2" in results
    assert "other:key" not in results


def test_template_rendering():
    """Verify standalone HTML template functions."""
    from anbar.templates import render_album_page, render_links_manage_page, render_password_page

    # Password page
    pw_html = render_password_page("obj123", "sig456", 1700000000, failed=True)
    assert "obj123" in pw_html or "sig456" in pw_html
    assert "display='block'" in pw_html

    # Album page escapes titles and filenames
    album_html = render_album_page(
        "<script>alert(1)</script>",
        [
            {
                "id": "o1",
                "name": "<b>evil</b>.png",
                "kind": "image",
                "size": 100,
                "url": "/f/o1",
                "thumb_url": "/t/o1",
            }
        ],
    )
    assert "<script>alert(1)</script>" not in album_html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in album_html
    assert "<b>evil</b>" not in album_html

    # Links manage page
    manage_html = render_links_manage_page(
        obj_id="o1",
        exp=1700000000,
        row={"filename": "doc.pdf"},
        opts="<option>test</option>",
        maxdl=3,
        fname="doc.pdf",
        pw_checked="checked",
        slug_js="doc-link",
    )
    assert "مدیریت لینک" in manage_html
    assert "doc.pdf" in manage_html


def test_healthz_deep_probe(client: TestClient):
    """Verify healthz basic and full deep diagnostics."""
    r = client.get("/healthz")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["service"] == "anbar"

    # Deep probe with full=1
    r_full = client.get("/healthz?full=1")
    assert r_full.status_code == 200
    full_data = r_full.json()
    assert full_data["status"] == "ok"
    assert full_data["checks"]["db"] == "ok"


def test_prometheus_metrics(client: TestClient):
    """Verify /metrics returns standard Prometheus formatted text."""
    # Upload a file to populate object count
    client.post(
        "/api/v1/upload",
        files={
            "file": (
                "metrics_test.bin",
                io.BytesIO(b"metrics_data_12345"),
                "application/octet-stream",
            )
        },
        headers=ADMIN,
    )

    r = client.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    text = r.text

    assert "anbar_objects_total" in text
    assert "anbar_objects_bytes_total" in text
    assert "anbar_chunk_cache_hits_total" in text
    assert "anbar_chunk_cache_misses_total" in text
    assert "anbar_chunk_cache_entries" in text
    assert "anbar_chunk_cache_bytes" in text
