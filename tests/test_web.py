"""F7 — Web UI: login flow, signed session cookie, cookie-authenticated API."""

from __future__ import annotations

ADMIN = "test-admin-key"
API = "test-key"


def _upload(client, name="ui-test.bin", size=4096) -> dict:
    r = client.post(
        "/api/v1/upload",
        files={"file": (name, b"x" * size)},
        headers={"Authorization": f"Bearer {API}"},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_login_rejects_wrong_key(client):
    r = client.post("/ui/login", json={"key": "nope"})
    assert r.status_code == 401
    assert "anbar_session" not in client.cookies


def test_login_sets_httponly_signed_cookie(client):
    r = client.post("/ui/login", json={"key": ADMIN})
    assert r.status_code == 200
    cookie = client.cookies.get("anbar_session")
    assert cookie and cookie.count(":") == 2  # {exp}:{tag}:{sig}
    # never the raw key itself
    assert ADMIN not in cookie


def test_me_reflects_session(client):
    assert client.get("/ui/me").json() == {"authed": False, "role": "anon"}
    client.post("/ui/login", json={"key": ADMIN})
    assert client.get("/ui/me").json() == {"authed": True, "role": "admin"}


def test_admin_list_via_cookie(client):
    up = _upload(client)
    client.post("/ui/login", json={"key": ADMIN})
    r = client.get("/api/v1/admin/objects")
    assert r.status_code == 200
    assert up["id"] in [o["id"] for o in r.json()["objects"]]


def test_download_via_cookie(client):
    up = _upload(client, name="dl.bin", size=1024)
    client.post("/ui/login", json={"key": ADMIN})
    r = client.get(f"/f/{up['id']}")
    assert r.status_code == 200
    assert len(r.content) == 1024


def test_delete_via_cookie(client):
    up = _upload(client, name="rm.bin")
    client.post("/ui/login", json={"key": ADMIN})
    r = client.delete(f"/f/{up['id']}")
    assert r.status_code == 200


def test_tampered_cookie_rejected(client):
    client.post("/ui/login", json={"key": ADMIN})
    cookie = client.cookies.get("anbar_session")
    exp, tag, sig = cookie.split(":")
    bad = f"{exp}:{tag}:{'0' * len(sig)}"
    # replace (not add): a browser jar holds ONE anbar_session; a second
    # .set() would append another cookie and the dup-tolerant whoami would
    # accept the still-valid first occurrence.
    for ck in [c_ for c_ in list(client.cookies.jar) if c_.name == "anbar_session"]:
        client.cookies.jar.clear(ck.domain, ck.path, ck.name)
    client.cookies.set("anbar_session", bad, domain="testserver", path="/")
    assert client.get("/ui/me").json()["authed"] is False
    assert client.get("/api/v1/admin/objects").status_code == 401


def test_logout_invalidates_session(client):
    client.post("/ui/login", json={"key": ADMIN})
    r = client.post("/ui/logout")
    assert r.status_code == 200
    assert client.get("/ui/me").json()["authed"] is False


def test_index_page_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "انبار" in r.text
    assert "ui/login" in r.text


def test_status_includes_max_upload_bytes(client):
    r = client.get("/api/v1/admin/status")
    assert r.status_code == 200
    assert r.json()["max_upload_bytes"] > 0
