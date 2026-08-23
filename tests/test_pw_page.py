"""v0.10.1: password unlock page for pw-protected links opened without ?pw."""
from __future__ import annotations

import io
import urllib.parse

ADMIN = {"Authorization": "Bearer test-admin-key"}


def _upload(client, name="secret.bin", content=b"top-secret-data"):
    r = client.post("/api/v1/upload", headers=ADMIN,
                    files={"file": (name, io.BytesIO(content), "application/octet-stream")})
    return r.json()["id"]


def _signed_url(client, oid, extra=""):
    """Mint a plain signed URL and return its path?query (has sig+exp)."""
    url = client.post(f"/f/{oid}/link?ttl=600{extra}", headers=ADMIN).json()["url"]
    u = urllib.parse.urlparse(url)
    return u.path + "?" + u.query


def test_browser_without_pw_gets_unlock_page(client):
    oid = _upload(client)
    client.post(f"/f/{oid}/link?ttl=600&password=hunter2&slug=vault",
                headers=ADMIN)
    base = _signed_url(client, oid)
    # browser visit → HTML unlock page, not a bare 403
    r = client.get(base, headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "رمز عبور".encode() in r.content or "رمزدار".encode() in r.content
    # pretty slug behaves the same for browsers
    r2 = client.get("/f/vault", headers={"Accept": "text/html"})
    assert r2.status_code == 200 and "text/html" in r2.headers["content-type"]


def test_curl_without_pw_still_403(client):
    oid = _upload(client)
    client.post(f"/f/{oid}/link?ttl=600&password=hunter2", headers=ADMIN)
    path = _signed_url(client, oid)
    # non-browser keeps the API behaviour: 403 password required
    assert client.get(path).status_code == 403
    # correct pw appended → bytes
    ok = client.get(path + "&pw=hunter2")
    assert ok.status_code == 200 and ok.content == b"top-secret-data"


def test_wrong_pw_shows_page_with_error_flag(client):
    oid = _upload(client)
    client.post(f"/f/{oid}/link?ttl=600&password=hunter2", headers=ADMIN)
    path = _signed_url(client, oid) + "&pw=WRONG"
    r = client.get(path, headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert b"badpw" in r.content or "اشتباه".encode() in r.content


def test_correct_pw_downloads_directly(client):
    """A pw link minted WITH a slug still serves bytes when ?pw matches.

    (The pretty slug alone never authenticates — the sig/exp from the minted
    URL are what count; the page flow appends ?pw to that same URL.)
    """
    oid = _upload(client, content=b"payload")
    path = _signed_url(client, oid)  # plain signed URL of this object
    client.post(f"/f/{oid}/link?ttl=600&password=pw123&slug=gated",
                headers=ADMIN)
    r = client.get(path + "&pw=pw123")
    assert r.status_code == 200 and r.content == b"payload"


def test_unlock_flow_via_signed_link(client):
    """Full visitor journey: open link → page → type pw → file bytes."""
    oid = _upload(client, content=b"final-check")
    client.post(f"/f/{oid}/link?ttl=600&password=s3cret&slug=journey",
                headers=ADMIN)
    path = _signed_url(client, oid)
    # step 1: open without pw → unlock page
    page = client.get(path, headers={"Accept": "text/html"})
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    # step 1b: opening the pretty slug shows the page too
    page2 = client.get("/f/journey", headers={"Accept": "text/html"})
    assert page2.status_code == 200
    # step 2: form submits the URL + &pw=s3cret → the file itself
    got = client.get(path + "&pw=s3cret")
    assert got.status_code == 200 and got.content == b"final-check"
