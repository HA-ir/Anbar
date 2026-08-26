"""v0.9.5: pretty link names (slugs) + ttl=0 "never" links."""

from __future__ import annotations

import io
import time

ADMIN = {"Authorization": "Bearer test-admin-key"}


def _upload(client, name="doc.bin", content=b"data"):
    r = client.post(
        "/api/v1/upload",
        headers=ADMIN,
        files={"file": (name, io.BytesIO(content), "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    obj = j.get("object") or j
    return obj.get("id") or obj.get("object_id")


def test_slug_mint_and_download(client):
    oid = _upload(client)
    r = client.post(f"/f/{oid}/link?ttl=600&slug=report-2026", headers=ADMIN)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["slug"] == "report-2026"
    assert j["pretty_url"].endswith("/f/report-2026")
    # pretty URL serves the file (signed link not required for slug path?
    # No — auth is ON in tests, so the slug alone must NOT grant access.)
    got = client.get("/f/report-2026")
    assert got.status_code == 401  # needs sig like any anonymous download


def test_slug_signed_link_roundtrip(client):
    oid = _upload(client)
    r = client.post(f"/f/{oid}/link?ttl=600&slug=pretty", headers=ADMIN).json()
    # mint a signed link too, then fetch via the pretty path with its query
    import urllib.parse

    u = urllib.parse.urlparse(r["url"])
    got = client.get("/f/pretty?" + u.query)
    assert got.status_code == 200, got.text
    assert got.content == b"data"


def test_slug_validation(client):
    oid = _upload(client)
    for bad in ("Report", "a b", "-lead", "x" * 65, ""):
        r = client.post(f"/f/{oid}/link?ttl=60&slug={bad}", headers=ADMIN)
        if bad == "":
            continue  # empty = no slug requested, plain link is fine
        assert r.status_code == 400, bad
    ok = client.post(f"/f/{oid}/link?ttl=60&slug=a-b_c9", headers=ADMIN)
    assert ok.status_code == 200


def test_slug_unique(client):
    o1 = _upload(client, name="one.bin")
    o2 = _upload(client, name="two.bin")
    r1 = client.post(f"/f/{o1}/link?ttl=60&slug=shared", headers=ADMIN)
    assert r1.status_code == 200
    # same object re-minting the same slug is idempotent
    again = client.post(f"/f/{o1}/link?ttl=60&slug=shared", headers=ADMIN)
    assert again.status_code == 200
    # another object may steal nothing
    r2 = client.post(f"/f/{o2}/link?ttl=60&slug=shared", headers=ADMIN)
    assert r2.status_code == 409


def test_slug_freed_on_delete(client):
    oid = _upload(client)
    client.post(f"/f/{oid}/link?ttl=60&slug=temp", headers=ADMIN)
    client.delete(f"/f/{oid}", headers=ADMIN)
    client.delete(f"/f/{oid}?purge=true", headers=ADMIN)  # v0.10: real destroy
    db = client.app.state.db
    assert db.kv_get("slug:temp") is None
    # and a new object can claim it
    o2 = _upload(client, name="new.bin")
    r = client.post(f"/f/{o2}/link?ttl=60&slug=temp", headers=ADMIN)
    assert r.status_code == 200


def test_ttl_zero_never_expires(client):
    oid = _upload(client)
    r = client.post(f"/f/{oid}/link?ttl=0", headers=ADMIN)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ttl_seconds"] > 50 * 365 * 86400  # practically never
    exp = j["expires_at"]
    assert exp > int(time.time()) + 50 * 365 * 86400
