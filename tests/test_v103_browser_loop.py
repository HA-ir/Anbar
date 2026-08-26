"""v0.10.3: browser journey with Accept: text/html must NOT loop the page.

Regression for 'entered correct password → wrong-password page again':
the precheck used bare sha256 instead of keyed HMAC, so it never matched
for real browsers (httpx tests don't send Accept: text/html and skipped
the precheck entirely).
"""

from __future__ import annotations

import io

BROWSER = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
ADMIN = {"Authorization": "Bearer test-admin-key"}


def _upload(client, content=b"real-browser-check"):
    r = client.post(
        "/api/v1/upload",
        headers=ADMIN,
        files={"file": (name_or(), io.BytesIO(content), "application/octet-stream")},
    )
    return r.json()["id"]


def name_or():
    return "loop.bin"


def test_correct_pw_via_browser_accept_serves_file(client):
    oid = _upload(client)
    client.post(f"/f/{oid}/link?ttl=600&password=r4z", headers=ADMIN)
    # 1) open signed link as a browser → unlock page
    url = client.post(f"/f/{oid}/link?ttl=600", headers=ADMIN).json()["url"]
    page = client.get(url, headers=BROWSER)
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    # 2) submit the form (correct pw, sig/exp carried)
    got = client.get(url + "&pw=r4z", headers=BROWSER)
    assert got.status_code == 200, "correct pw must serve the file"
    assert got.content == b"real-browser-check"


def test_wrong_pw_still_shows_error_page(client):
    oid = _upload(client)
    client.post(f"/f/{oid}/link?ttl=600&password=r4z", headers=ADMIN)
    url = client.post(f"/f/{oid}/link?ttl=600", headers=ADMIN).json()["url"]
    got = client.get(url + "&pw=WRONG", headers=BROWSER)
    assert got.status_code == 200
    assert b"err.style.display='block'" in got.content


def test_correct_pw_with_slug_via_browser(client):
    """Slug journey: open /f/name → page → submit → file bytes."""
    oid = _upload(client)
    client.post(f"/f/{oid}/link?ttl=600&password=k2&slug=loopslug", headers=ADMIN)
    page = client.get("/f/loopslug", headers=BROWSER)
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    import re

    sig = re.search(r'name="sig" value="([^"]+)"', page.text).group(1)
    exp = re.search(r'name="exp" value="(\d+)"', page.text).group(1)
    got = client.get(f"/f/loopslug?sig={sig}&exp={exp}&pw=k2", headers=BROWSER)
    assert got.status_code == 200 and got.content == b"real-browser-check"
