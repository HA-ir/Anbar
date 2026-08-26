"""F4: auth matrix, signed links, runtime toggle, rotation, ownership, listing."""

from __future__ import annotations

import time

from tests.test_download import ADMIN, AUTH

API = "test-key"
ADMIN_KEY = "test-admin-key"
OTHER_KEY = "another-key"  # a second, distinct uploader key


def _upload(client, headers=AUTH, name="auth.bin", payload=None):
    p = payload if payload is not None else b"hello-auth" * 1000
    r = client.post(
        "/api/v1/upload",
        files={"file": (name, p, "application/octet-stream")},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ── upload auth ──────────────────────────────────────────────────────────────
def test_upload_requires_key(backend, client):
    r = client.post("/api/v1/upload", files={"file": ("a", b"x", "application/octet-stream")})
    assert r.status_code == 401


def test_upload_with_key(backend, client):
    assert _upload(client) is not None


def test_upload_with_wrong_key(backend, client):
    r = client.post(
        "/api/v1/upload",
        files={"file": ("a", b"x", "application/octet-stream")},
        headers={"Authorization": f"Bearer {OTHER_KEY}"},
    )
    assert r.status_code == 401


# ── download auth matrix ─────────────────────────────────────────────────────
def test_download_anon_rejected(backend, client):
    obj = _upload(client)
    assert client.get(f"/f/{obj}").status_code == 401


def test_download_with_bearer_key(backend, client):
    obj = _upload(client)
    assert client.get(f"/f/{obj}", headers=AUTH).status_code == 200
    assert client.get(f"/f/{obj}", headers=ADMIN).status_code == 200


def test_download_with_signed_link(backend, client):
    obj = _upload(client)
    url = client.post(f"/f/{obj}/link", headers=AUTH).json()["url"]
    r = client.get(url)  # no bearer — signed link alone must work
    assert r.status_code == 200
    assert r.content == b"hello-auth" * 1000


def test_download_bad_signature(backend, client):
    obj = _upload(client)
    r = client.get(f"/f/{obj}?sig={'0' * 64}&exp={int(time.time()) + 60}")
    assert r.status_code == 403


def test_download_expired_link(backend, client):
    obj = _upload(client)
    from anbar.auth import sign

    exp = int(time.time()) - 10
    sig = sign(obj, exp, "test-hmac-secret")
    assert client.get(f"/f/{obj}?sig={sig}&exp={exp}").status_code == 410


def test_link_mint_requires_key(backend, client):
    obj = _upload(client)
    assert client.post(f"/f/{obj}/link").status_code == 401


def test_link_mint_ttl_clamped(backend, client):
    obj = _upload(client)
    body = client.post(f"/f/{obj}/link", params={"ttl": 1}, headers=AUTH).json()
    assert body["ttl_seconds"] == 60  # clamped to minimum
    assert "sig=" in body["url"] and "exp=" in body["url"]


# ── runtime toggle (no restart) ─────────────────────────────────────────────
def test_auth_toggle_off_then_on(backend, client):
    obj = _upload(client)
    assert client.get(f"/f/{obj}").status_code == 401

    r = client.post("/api/v1/admin/auth/toggle", headers=ADMIN)
    assert r.status_code == 200 and r.json()["auth_enabled"] is False
    # now open: no key, no signature
    assert client.get(f"/f/{obj}").status_code == 200
    # status reflects the toggle
    assert client.get("/api/v1/admin/status").json()["auth_enabled"] is False

    # flip back
    r = client.post("/api/v1/admin/auth/toggle", headers=ADMIN)
    assert r.json()["auth_enabled"] is True
    assert client.get(f"/f/{obj}").status_code == 401


def test_auth_toggle_requires_admin(backend, client):
    assert client.post("/api/v1/admin/auth/toggle").status_code == 401
    assert client.post("/api/v1/admin/auth/toggle", headers=AUTH).status_code == 403


# ── secret rotation ─────────────────────────────────────────────────────────
def test_rotate_secret_invalidates_old_links(backend, client):
    obj = _upload(client)
    old_url = client.post(f"/f/{obj}/link", headers=AUTH).json()["url"]
    assert client.get(old_url).status_code == 200

    r = client.post("/api/v1/admin/auth/rotate-secret", headers=ADMIN)
    assert r.status_code == 200 and "hmac_secret" in r.json()

    # old link is now invalid; new link works with the new secret
    assert client.get(old_url).status_code == 403
    new_url = client.post(f"/f/{obj}/link", headers=AUTH).json()["url"]
    assert client.get(new_url).status_code == 200


# ── ownership & admin endpoints ─────────────────────────────────────────────
def test_delete_owner(backend, client):
    """With a single API key, the uploader owns everything it uploaded."""
    obj = _upload(client, headers=AUTH)
    assert client.delete(f"/f/{obj}", headers=AUTH).status_code == 200
    # v0.10: first delete trashes; the row survives until purged
    assert client.delete(f"/f/{obj}?purge=true", headers=AUTH).status_code == 200
    # gone for real now
    assert client.delete(f"/f/{obj}", headers=AUTH).status_code == 404


def test_delete_anon_and_unknown_key(backend, client):
    obj = _upload(client, headers=AUTH)
    assert client.delete(f"/f/{obj}").status_code == 401
    # a key that is neither api nor admin resolves to anon -> 401
    unknown = {"Authorization": f"Bearer {OTHER_KEY}"}
    assert client.delete(f"/f/{obj}", headers=unknown).status_code == 401
    # admin can always delete
    assert client.delete(f"/f/{obj}", headers=ADMIN).status_code == 200


def test_objects_listing_admin_only(backend, client):
    _upload(client)
    assert client.get("/api/v1/admin/objects").status_code == 401
    assert client.get("/api/v1/admin/objects", headers=AUTH).status_code == 403
    r = client.get("/api/v1/admin/objects", headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert all("manifest" not in o and "uploader_key" not in o for o in body["objects"])
