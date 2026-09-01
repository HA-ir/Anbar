"""v0.15.35 — UI/UX round: albums in links manager, EN-only album pages,
restart support, trash UX, gallery chrome for empty folders."""
from __future__ import annotations

from starlette.testclient import TestClient

UP = {"Authorization": "Bearer test-admin-key"}


def _upload(client: TestClient, name: str) -> str:
    obj = client.post(
        "/api/v1/upload/raw",
        content=b"Z" * 16,
        headers={**UP, "X-File-Name": name, "Content-Type": "text/plain"},
    ).json()
    return obj["id"]


def test_album_links_appear_in_links_manager(client: TestClient):
    a = _upload(client, "fold/a1.txt")
    b = _upload(client, "fold/a2.txt")
    r = client.post("/f/album", headers=UP, json={"ids": [a, b], "ttl": 3600})
    assert r.status_code == 200
    token = r.json()["token"]
    links = client.get("/api/v1/admin/links", headers=UP).json()["links"]
    albums = [x for x in links if x.get("album")]
    assert any(x["slug"] == token for x in albums)
    row = next(x for x in albums if x["slug"] == token)
    assert row["album_count"] == 2
    assert row["exp"] > 0


def test_album_revoke_endpoint(client: TestClient):
    a = _upload(client, "rv/x.txt")
    r = client.post("/f/album", headers=UP, json={"ids": [a], "ttl": 3600})
    token = r.json()["token"]
    page = client.get(f"/f/a/{token}")
    assert page.status_code == 200
    rv = client.post(f"/api/v1/admin/album/{token}/revoke", headers=UP)
    assert rv.status_code == 200
    assert client.get(f"/f/a/{token}").status_code == 404
    # second revoke → 404 unknown
    assert client.post(f"/api/v1/admin/album/{token}/revoke", headers=UP).status_code == 404


def test_album_page_english_only(client: TestClient):
    a = _upload(client, "en/x.txt")
    r = client.post("/f/album", headers=UP, json={"ids": [a], "ttl": 3600})
    token = r.json()["token"]
    page = client.get(f"/f/a/{token}")
    body = page.text
    assert 'lang="en"' in body
    assert 'dir="rtl"' not in body
    assert "دانلود" not in body and "نمایش" not in body
    assert "Download" in body and "files · anbar" in body
