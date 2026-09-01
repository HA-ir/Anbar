"""v0.15.33 — folder ZIP/share rejected freshly-filled folders.

Folder actions built their id list from the UI's client-side `files[]`
cache (capped at 500 rows, refreshed lazily). If the user uploaded files
into a folder and immediately hit ZIP/share on the folder card (or the
upload came from another tab/session), the stale cache had no rows under
that prefix and the UI showed the misleading toasts:
  «دانلود زیپ فقط برای فایل هاست» / «اشتراک گروهی فقط برای فایل هاست»
The example folder the user had validated earlier kept working — only
"new" folders appeared broken.

Fix (two layers):
* `GET /api/v1/admin/objects?prefix=<p>` — server-side, authoritative
  prefix filter (db.list_objects_by_prefix), excluding the folder marker.
* UI `serverFolderIds()` — folder ZIP and folder-share submit now fetch
  fresh ids from the server, falling back to the old cache only if the
  API itself fails. shareFolder() no longer pre-blocks with the toast.
"""
from __future__ import annotations

from starlette.testclient import TestClient

UP = {"Authorization": "Bearer test-admin-key"}


def _upload(client: TestClient, name: str) -> str:
    obj = client.post(
        "/api/v1/upload/raw",
        content=b"P" * 32,
        headers={**UP, "X-File-Name": name, "Content-Type": "application/octet-stream"},
    ).json()
    return obj["id"]


def test_admin_objects_prefix_filter(client: TestClient):
    a = _upload(client, "fresh/x1.bin")
    b = _upload(client, "fresh/x2.bin")
    _upload(client, "other/y.bin")
    r = client.get(
        "/api/v1/admin/objects?limit=500&prefix=fresh", headers=UP
    )
    assert r.status_code == 200
    ids = [o["id"] for o in r.json()["objects"]]
    # both files under the prefix are returned, nothing else
    assert set(ids) == {a, b}


def test_admin_objects_prefix_excludes_folder_marker(client: TestClient):
    # folder marker object (filename ends with '/')
    r = client.post(
        "/api/v1/admin/folders/create",
        json={"path": "marktest"},
        headers=UP,
    )
    assert r.status_code == 200
    _upload(client, "marktest/inner.bin")
    r = client.get(
        "/api/v1/admin/objects?limit=500&prefix=marktest", headers=UP
    )
    rows = r.json()["objects"]
    names = [o["filename"] for o in rows]
    assert "marktest/inner.bin" in names
    # the folder marker itself must not be in the id list (it would
    # poison /f/zip and /f/album)
    assert "marktest/" not in names


def test_prefix_and_no_prefix_interchangeable(client: TestClient):
    o1 = _upload(client, "mix/a.bin")
    r = client.get("/api/v1/admin/objects?limit=500", headers=UP)
    assert r.status_code == 200  # plain listing still works
    r2 = client.get("/api/v1/admin/objects?limit=500&prefix=mix", headers=UP)
    assert [o["id"] for o in r2.json()["objects"]] == [o1]
