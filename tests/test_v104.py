"""v0.10.4: gallery audio/pdf previews, per-link stats, shared albums."""

from __future__ import annotations

import io

ADMIN = {"Authorization": "Bearer test-admin-key"}
BROWSER = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


def _upload(client, name, content, ct="application/octet-stream"):
    r = client.post(
        "/api/v1/upload", headers=ADMIN, files={"file": (name, io.BytesIO(content), ct)}
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_link_stats_count_downloads(client):
    """Full downloads via a signed link bump that link's counter."""
    oid = _upload(client, "s.txt", b"stats-check")
    m = client.post(f"/f/{oid}/link?ttl=600", headers=ADMIN).json()
    url = m["url"]
    client.get(url)
    client.get(url)
    links = client.get("/api/v1/admin/links", headers=ADMIN).json()["links"]
    row = next(x for x in links if x["obj_id"] == oid)
    assert row["downloads"] == 2


def test_range_requests_do_not_count(client):
    oid = _upload(client, "r.bin", b"0123456789")
    url = client.post(f"/f/{oid}/link?ttl=600", headers=ADMIN).json()["url"]
    client.get(url, headers={"Range": "bytes=0-3"})
    links = client.get("/api/v1/admin/links", headers=ADMIN).json()["links"]
    row = next(x for x in links if x["obj_id"] == oid)
    assert row["downloads"] == 0  # partial fetches don't count


def test_album_create_and_page(client):
    o1 = _upload(client, "a.png", b"\x89PNG fake", "image/png")
    o2 = _upload(client, "b.mp3", b"ID3 fake", "audio/mpeg")
    r = client.post("/f/album", headers=ADMIN, json={"ids": [o1, o2], "title": "تست آلبوم"})
    assert r.status_code == 200
    j = r.json()
    assert j["count"] == 2 and "/f/a/" in j["url"]
    token = j["token"]
    page = client.get(f"/f/a/{token}", headers=BROWSER)
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert "تست آلبوم".encode() in page.content
    # items embedded with signed urls
    assert b'"kind": "image"' in page.content or '"kind":"image"' in page.content
    assert b"a.png" in page.content and b"b.mp3" in page.content


def test_album_requires_admin_and_validates(client):
    assert client.post("/f/album", json={"ids": ["x"]}).status_code == 401
    # admin but no valid ids → 404
    r = client.post("/f/album", headers=ADMIN, json={"ids": ["nope12345678"]})
    assert r.status_code == 404
    # empty body → 400
    assert client.post("/f/album", headers=ADMIN, json={"ids": []}).status_code == 400


def test_album_missing_token_404(client):
    r = client.get("/f/a/nosuchtoken123", headers=BROWSER)
    assert r.status_code == 404
    assert "موجود نیست".encode() in r.content


def test_album_hides_deleted_files(client):
    o1 = _upload(client, "keep.txt", b"k")
    o2 = _upload(client, "gone.txt", b"g")
    tok = client.post("/f/album", headers=ADMIN, json={"ids": [o1, o2]}).json()["token"]
    client.delete(f"/f/{o2}", headers=ADMIN)  # trash it
    page = client.get(f"/f/a/{tok}")
    assert b"keep.txt" in page.content
    assert b"gone.txt" not in page.content


def test_gallery_html_has_audio_pdf_blocks(client):
    """The UI ships real audio/PDF gallery thumbs (not bare ♪ icons)."""
    from anbar.api.web import _render

    html = _render()
    assert 'class="gaudio"' in html and "<audio" in html
    assert 'class="gpdf"' in html
