"""v0.15.32 — album gallery page rendered ZERO items.

The gallery script did `JSON.parse(__PAYLOAD__)` but the payload was embedded
as a bare JSON array literal (json.dumps output, not a quoted string), so
`JSON.parse([{...},...])` threw "Unexpected token" -> the whole <script> died
-> #grid stayed empty ("files in the shared folder do not show").
Fix: embed the payload directly as `const ITEMS = __PAYLOAD__;`.
"""
from __future__ import annotations

from starlette.testclient import TestClient

UP = {"Authorization": "Bearer test-admin-key"}


def _upload(client: TestClient, name: str) -> str:
    obj = client.post(
        "/api/v1/upload/raw",
        content=b"Z" * 64,
        headers={**UP, "X-File-Name": name, "Content-Type": "application/octet-stream"},
    ).json()
    return obj["id"]


def test_album_items_parse_without_json_parse_wrapper(client: TestClient):
    o1 = _upload(client, "one.bin")
    o2 = _upload(client, "two.bin")
    r = client.post(
        "/f/album",
        json={"ids": [o1, o2]},
        headers=UP,
    )
    assert r.status_code == 200
    token = r.json()["token"]
    page = client.get(f"/f/a/{token}")
    assert page.status_code == 200
    body = page.text
    # the payload must be embedded as a bare JS array literal
    assert "const ITEMS = [" in body
    # the broken wrapper must be gone
    assert "JSON.parse([" not in body
    # both filenames are in the payload
    assert "one.bin" in body
    assert "two.bin" in body


def test_album_page_items_structure_valid(client: TestClient):
    o1 = _upload(client, "x.bin")
    r = client.post("/f/album", json={"ids": [o1]}, headers=UP)
    token = r.json()["token"]
    body = client.get(f"/f/a/{token}").text
    # extract the embedded array and check its shape (id/name/sig present)
    start = body.index("const ITEMS = [") + len("const ITEMS = ")
    end = body.index("];", start) + 1
    import json
    items = json.loads(body[start:end])
    assert len(items) == 1
    it = items[0]
    assert it["id"] == o1
    assert it["name"]
    assert len(it["sig"]) == 64
