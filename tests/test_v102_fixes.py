"""v0.10.2 fixes: unlock form keeps sig/exp + eye toggle; live-only listing."""
from __future__ import annotations

import io
import urllib.parse

ADMIN = {"Authorization": "Bearer test-admin-key"}


def _upload(client, name="f.bin", content=b"data"):
    r = client.post("/api/v1/upload", headers=ADMIN,
                    files={"file": (name, io.BytesIO(content), "application/octet-stream")})
    return r.json()["id"]


def _signed(client, oid):
    url = client.post(f"/f/{oid}/link?ttl=600", headers=ADMIN).json()["url"]
    u = urllib.parse.urlparse(url)
    return u.path + "?" + u.query


def test_unlock_form_keeps_sig_exp(client):
    """The unlock page's form must carry sig/exp (a bare ?pw= would 401)."""
    oid = _upload(client)
    client.post(f"/f/{oid}/link?ttl=600&password=abc&slug=formsig",
                headers=ADMIN)
    path = _signed(client, oid)  # visit the signed URL like a real user
    r = client.get(path, headers={"Accept": "text/html"})
    assert r.status_code == 200
    # hidden fields present with values
    assert b'name="sig"' in r.content and b'name="exp"' in r.content
    assert b'value=""' not in r.content  # never empty sig/exp
    # extract hidden values and simulate the form submission
    import re

    html = r.text
    sig = re.search(r'name="sig" value="([^"]+)"', html).group(1)
    exp = re.search(r'name="exp" value="([^"]+)"', html).group(1)
    submit = f"/f/formsig?sig={sig}&exp={exp}&pw=abc"
    got = client.get(submit)
    assert got.status_code == 200 and got.content == b"data"


def test_unlock_from_slug_gets_fresh_window(client):
    """Opening via pretty slug: page mints a fresh 1h window in its form."""
    oid = _upload(client)
    client.post(f"/f/{oid}/link?ttl=600&password=k1&slug=freshwin",
                headers=ADMIN)
    r = client.get("/f/freshwin", headers={"Accept": "text/html"})
    assert r.status_code == 200
    import re

    html = r.text
    sig = re.search(r'name="sig" value="([^"]+)"', html).group(1)
    exp = int(re.search(r'name="exp" value="(\d+)"', html).group(1))
    import time as t

    assert exp - int(t.time()) > 3000  # ~1h window minted
    got = client.get(f"/f/freshwin?sig={sig}&exp={exp}&pw=k1")
    assert got.status_code == 200 and got.content == b"data"


def test_wrong_pw_page_has_error_and_eye(client):
    oid = _upload(client)
    client.post(f"/f/{oid}/link?ttl=600&password=k1", headers=ADMIN)
    path = _signed(client, oid) + "&pw=WRONG"
    r = client.get(path, headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert b"err.style.display='block'" in r.content  # server-driven error
    assert b"eyebtn" in r.content and b"eye-shut" in r.content


def test_revoked_link_hidden_after_refresh(client):
    """Live view: revoked links disappear from /admin/links for good."""
    o1 = _upload(client)
    o2 = _upload(client)
    url1 = client.post(f"/f/{o1}/link?ttl=3600&slug=a-live",
                       headers=ADMIN).json()
    exp1 = int(url1["expires_at"])
    client.post(f"/f/{o2}/link?ttl=3600&slug=b-live", headers=ADMIN)
    client.post(f"/api/v1/admin/links/{o1}/revoke/{exp1}", headers=ADMIN)
    # default listing shows only the live one — even after repeated calls
    for _ in range(3):  # refresh x3
        rows = client.get("/api/v1/admin/links", headers=ADMIN).json()["links"]
        slugs = [r["slug"] for r in rows]
        assert "b-live" in slugs and "a-live" not in slugs
        assert all(not r["revoked"] and not r["expired"] for r in rows)


def test_view_param_serves_inline(client):
    oid = _upload(client, content=b"inline-please")
    url = client.post(f"/f/{oid}/link?ttl=600&slug=inl", headers=ADMIN).json()
    base = urllib.parse.urlparse(url["url"])
    plain = client.get(base.path + "?" + base.query)
    view = client.get(base.path + "?" + base.query + "&view=1")
    assert "attachment" in plain.headers["content-disposition"]
    assert "inline" in view.headers["content-disposition"]
    assert view.content == b"inline-please"
