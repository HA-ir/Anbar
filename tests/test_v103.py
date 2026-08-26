"""v0.10.3: link manager page (re-mint with new settings) + browser pw loop fix."""

from __future__ import annotations

import io
import re

ADMIN = {"Authorization": "Bearer test-admin-key"}
BROWSER = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


def _upload(client, content=b"manage-me"):
    r = client.post(
        "/api/v1/upload",
        headers=ADMIN,
        files={"file": ("doc.txt", io.BytesIO(content), "application/octet-stream")},
    )
    return r.json()["id"]


def test_manage_page_renders_settings(client):
    oid = _upload(client)
    m = client.post(f"/f/{oid}/link?ttl=3600&password=pp1&max_dl=3", headers=ADMIN).json()
    exp = int(m["expires_at"])
    r = client.get(f"/api/v1/admin/links/{oid}/manage?exp={exp}", headers=ADMIN)
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "مدیریت لینک".encode() in r.content
    assert b"checked" in r.content  # pw box pre-checked
    assert b'value="3"' in r.content  # max_dl prefilled
    assert b"doc.txt" in r.content


def test_manage_page_requires_admin(client):
    oid = _upload(client)
    m = client.post(f"/f/{oid}/link?ttl=600", headers=ADMIN).json()
    exp = int(m["expires_at"])
    assert client.get(f"/api/v1/admin/links/{oid}/manage?exp={exp}").status_code == 401


def test_manage_page_unknown_link_404(client):
    r = client.get("/api/v1/admin/links/nope12345678/manage?exp=123", headers=ADMIN)
    assert r.status_code == 404


def test_manage_flow_revoke_then_remint(client):
    """The exact flow the page performs: revoke old → mint new w/ same slug."""
    oid = _upload(client)
    m = client.post(f"/f/{oid}/link?ttl=3600&slug=mng&password=old", headers=ADMIN).json()
    exp = int(m["expires_at"])
    # 1. revoke old
    rv = client.post(f"/api/v1/admin/links/{oid}/revoke/{exp}", headers=ADMIN)
    assert rv.status_code == 200
    # 2. mint new with same slug, new password, longer ttl, cap
    nm = client.post(f"/f/{oid}/link?ttl=604800&slug=mng&password=new&max_dl=5", headers=ADMIN)
    assert nm.status_code == 200
    j = nm.json()
    assert j["slug"] == "mng" and j.get("password_protected") is True
    # 3. new link works, old is dead
    import urllib.parse

    u = urllib.parse.urlparse(j["url"])
    ok = client.get(u.path + "?" + u.query + "&pw=new")
    assert ok.status_code == 200 and ok.content == b"manage-me"


def test_browser_correct_pw_no_loop(client):
    """Regression: correct pw via real-browser Accept header serves bytes."""
    oid = _upload(client, content=b"no-loop")
    url = client.post(f"/f/{oid}/link?ttl=600&password=r4z", headers=ADMIN).json()["url"]
    page = client.get(url, headers=BROWSER)
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    got = client.get(url + "&pw=r4z", headers=BROWSER)
    assert got.status_code == 200 and got.content == b"no-loop"


def test_browser_wrong_pw_shows_error(client):
    oid = _upload(client, content=b"wrong-pw-check")
    url = client.post(f"/f/{oid}/link?ttl=600&password=r4z", headers=ADMIN).json()["url"]
    got = client.get(url + "&pw=nope", headers=BROWSER)
    assert got.status_code == 200
    assert b"err.style.display='block'" in got.content


def test_slug_journey_via_browser(client):
    oid = _upload(client, content=b"slug-journey")
    client.post(f"/f/{oid}/link?ttl=600&password=k3&slug=journey103", headers=ADMIN)
    page = client.get("/f/journey103", headers=BROWSER)
    assert page.status_code == 200
    sig = re.search(r'name="sig" value="([^"]+)"', page.text).group(1)
    exp = re.search(r'name="exp" value="(\d+)"', page.text).group(1)
    got = client.get(f"/f/journey103?sig={sig}&exp={exp}&pw=k3", headers=BROWSER)
    assert got.status_code == 200 and got.content == b"slug-journey"
