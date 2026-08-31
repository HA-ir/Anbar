"""BUG-v0.15.26: download counter accuracy.

Opening a media preview sends Range requests (206) — the browser's
<video preload="metadata"> and seek probes must NOT count as downloads.
Only a full 200 body bumps the counter (and per-link stats/caps).
"""

from __future__ import annotations

from tests.test_download import ADMIN, AUTH, _upload


def _row(client, obj: str) -> dict:
    r = client.get("/api/v1/admin/objects?limit=500", headers=ADMIN)
    assert r.status_code == 200
    for o in r.json()["objects"]:
        if o["id"] == obj:
            return o
    raise AssertionError(f"object {obj} not in listing")


def _signed_url(client, obj: str) -> str:
    r = client.post(f"/f/{obj}/link", headers=AUTH)
    assert r.status_code == 200
    return r.json()["url"]


def test_range_requests_do_not_bump_counter(backend, client):
    obj = _upload(client)
    url = _signed_url(client, obj)
    assert _row(client, obj)["downloaded"] == 0

    r = client.get(url, headers={"Range": "bytes=0-99"})
    assert r.status_code == 206
    assert _row(client, obj)["downloaded"] == 0

    r = client.get(url, headers={"Range": "bytes=1000-1999"})
    assert r.status_code == 206
    assert _row(client, obj)["downloaded"] == 0


def test_full_download_bumps_once(backend, client):
    obj = _upload(client)
    url = _signed_url(client, obj)
    assert client.get(url).status_code == 200
    assert _row(client, obj)["downloaded"] == 1
    # a second full download counts again
    assert client.get(url).status_code == 200
    assert _row(client, obj)["downloaded"] == 2
    # and a range probe afterwards still does not count
    client.get(url, headers={"Range": "bytes=0-9"})
    assert _row(client, obj)["downloaded"] == 2


def test_304_revalidation_does_not_bump(backend, client):
    obj = _upload(client)
    url = _signed_url(client, obj)
    first = client.get(url)
    assert first.status_code == 200
    etag = first.headers.get("etag")
    assert etag
    r = client.get(url, headers={"If-None-Match": etag})
    assert r.status_code == 304
    assert _row(client, obj)["downloaded"] == 1
