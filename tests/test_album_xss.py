"""Regression: album page (/f/a/<token>) must escape item filenames.

Stored filenames are arbitrary uploader input; the gallery script injects
`it.name` via innerHTML, so an unescaped name was a stored XSS on the
public share page.
"""

from fastapi.testclient import TestClient


def _upload(client: TestClient, name: str, body: bytes = b"x") -> dict:
    r = client.post(
        "/api/v1/upload",
        files={"file": (name, body, "image/png")},
        headers={"Authorization": "Bearer test-admin-key"},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_album_escapes_malicious_filename(client: TestClient):
    evil = '<img src=x onerror=alert(1)>.png'
    obj = _upload(client, evil)
    r = client.post(
        "/f/album",
        json={"ids": [obj["id"]], "title": "t"},
        headers={"Authorization": "Bearer test-admin-key"},
    )
    assert r.status_code == 200, r.text
    token = r.json()["token"]

    page = client.get(f"/f/a/{token}")
    assert page.status_code == 200
    body = page.text
    # The raw payload must NOT survive into the HTML
    assert "<img src=x onerror=alert(1)>" not in body
    # Escaped form must be present in the embedded JSON payload
    assert "&lt;img src=x onerror=alert(1)&gt;" in body


def test_album_normal_filename_untouched(client: TestClient):
    obj = _upload(client, "photo.png")
    r = client.post(
        "/f/album",
        json={"ids": [obj["id"]]},
        headers={"Authorization": "Bearer test-admin-key"},
    )
    assert r.status_code == 200
    page = client.get(f"/f/a/{r.json()['token']}")
    assert "photo.png" in page.text


def test_album_title_escaped(client: TestClient):
    obj = _upload(client, "a.png")
    r = client.post(
        "/f/album",
        json={"ids": [obj["id"]], "title": "<script>x</script>"},
        headers={"Authorization": "Bearer test-admin-key"},
    )
    assert r.status_code == 200
    page = client.get(f"/f/a/{r.json()['token']}")
    assert "<script>x</script>" not in page.text
