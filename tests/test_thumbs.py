"""PERF-03: upload-time thumbnails + GET /f/{id}/thumb."""

from __future__ import annotations

import io
import time

from PIL import Image

from anbar import thumbs


def _png_bytes(w=800, h=600, color=(200, 40, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def _upload_image(client, data: bytes, name="pic.png", ct="image/png"):
    return client.post(
        "/api/v1/upload",
        files={"file": (name, data, ct)},
        headers={"Authorization": "Bearer test-admin-key"},
    )


def test_thumb_generated_on_upload_and_served(client):
    r = _upload_image(client, _png_bytes())
    assert r.status_code == 200, r.text
    obj_id = r.json()["id"]

    # generation is a background task — poll briefly for it
    deadline = time.time() + 5
    served = None
    while time.time() < deadline:
        t = client.get(f"/f/{obj_id}/thumb", headers={"Authorization": "Bearer test-admin-key"})
        if t.status_code == 200:
            served = t
            break
        time.sleep(0.05)
    assert served is not None, "thumbnail never appeared within 5s"
    assert served.headers["content-type"].startswith("image/")
    assert served.headers.get("x-content-type-options") == "nosniff"
    # decoded thumb is ≤256px
    im = Image.open(io.BytesIO(served.content))
    assert max(im.size) <= thumbs.THUMB_MAX_PX


def test_thumb_404_for_non_image_and_auth_matrix(client):
    # non-image upload → no thumb ever
    r = _upload_image(client, b"plain text", name="x.txt", ct="text/plain")
    assert r.status_code == 200
    obj_id = r.json()["id"]
    time.sleep(0.2)
    assert (
        client.get(f"/f/{obj_id}/thumb", headers={"Authorization": "Bearer test-admin-key"}).status_code
        == 404
    )

    # corrupt "image" upload must not break anything; no thumb either
    r2 = _upload_image(client, b"not-an-image", name="y.png", ct="image/png")
    assert r2.status_code == 200
    time.sleep(0.2)
    assert (
        client.get(f"/f/{r2.json()['id']}/thumb", headers={"Authorization": "Bearer test-admin-key"}).status_code
        == 404
    )

    # auth: anon is rejected when auth is on
    assert client.get(f"/f/{obj_id}/thumb").status_code == 401


def test_thumb_auth_via_signed_link(client):
    r = _upload_image(client, _png_bytes())
    obj_id = r.json()["id"]
    # mint via the API — signature format stays internal
    link = client.post(f"/f/{obj_id}/link", headers={"Authorization": "Bearer test-admin-key"})
    assert link.status_code == 200, link.text
    body = link.json()
    url = body.get("url") or body.get("link")
    assert url, body
    path = url.split("/f/")[-1] if "/f/" in url else url.lstrip("/")
    t = client.get(f"/f/{path}" if not path.startswith("http") else url)
    assert t.status_code in (200, 302, 307)


def test_purge_removes_thumb(client):
    r = _upload_image(client, _png_bytes())
    obj_id = r.json()["id"]
    settings = client.app.state.settings
    deadline = time.time() + 5
    while time.time() < deadline and not thumbs.has_thumb(settings, obj_id):
        time.sleep(0.05)
    assert thumbs.has_thumb(settings, obj_id)

    d = client.delete(
        f"/f/{obj_id}?purge=true", headers={"Authorization": "Bearer test-admin-key"}
    )
    assert d.status_code == 200, d.text
    assert not thumbs.has_thumb(settings, obj_id)


def test_objects_list_has_thumb_flag(client):
    r = _upload_image(client, _png_bytes())
    obj_id = r.json()["id"]
    row = None
    deadline = time.time() + 5
    while time.time() < deadline:
        rows = client.get(
            "/api/v1/admin/objects?limit=10", headers={"Authorization": "Bearer test-admin-key"}
        ).json()["objects"]
        row = next((x for x in rows if x["id"] == obj_id), None)
        if row and row.get("hasThumb"):
            break
        time.sleep(0.05)
    assert row is not None, "object missing from listing"
    assert row.get("hasThumb") is True, "content_type must reach the flag via list_objects"
