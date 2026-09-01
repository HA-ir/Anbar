"""v0.15.36 — Revoke-all covers albums; album rows show folder name only."""
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


def test_revoke_all_kills_albums_too(client: TestClient):
    a = _upload(client, "f1/x.txt")
    b = _upload(client, "f2/y.txt")
    t1 = client.post("/f/album", headers=UP, json={"ids": [a], "ttl": 3600}).json()["token"]
    t2 = client.post("/f/album", headers=UP, json={"ids": [b], "ttl": 3600}).json()["token"]
    assert client.get(f"/f/a/{t1}").status_code == 200
    r = client.post("/api/v1/admin/links/revoke-all", headers=UP)
    assert r.status_code == 200
    assert r.json()["count"] >= 2
    # BUG-v0.15.36: albums must die with everything else
    assert client.get(f"/f/a/{t1}").status_code == 404
    assert client.get(f"/f/a/{t2}").status_code == 404
    links = client.get("/api/v1/admin/links", headers=UP).json()["links"]
    assert not [x for x in links if x.get("album")]


def test_album_row_label_is_folder_name_only(client: TestClient):
    a = _upload(client, "myfolder/shot1.png")
    b = _upload(client, "myfolder/shot2.png")
    c = _upload(client, "myfolder/deep/shot3.png")
    tok = client.post("/f/album", headers=UP, json={"ids": [a, b, c], "ttl": 3600}).json()["token"]
    links = client.get("/api/v1/admin/links", headers=UP).json()["links"]
    row = next(x for x in links if x.get("album") and x["slug"] == tok)
    # single top-level folder → just the folder name, no file names
    assert row["filename"] == "myfolder"


def test_album_row_label_root_files(client: TestClient):
    a = _upload(client, "loose1.txt")
    b = _upload(client, "loose2.txt")
    tok = client.post("/f/album", headers=UP, json={"ids": [a, b], "ttl": 3600}).json()["token"]
    links = client.get("/api/v1/admin/links", headers=UP).json()["links"]
    row = next(x for x in links if x.get("album") and x["slug"] == tok)
    assert row["filename"] == "loose1.txt / loose2.txt"


def test_album_row_label_multiple_folders(client: TestClient):
    a = _upload(client, "alfa/1.txt")
    b = _upload(client, "beta/2.txt")
    tok = client.post("/f/album", headers=UP, json={"ids": [a, b], "ttl": 3600}).json()["token"]
    links = client.get("/api/v1/admin/links", headers=UP).json()["links"]
    row = next(x for x in links if x.get("album") and x["slug"] == tok)
    assert row["filename"] == "alfa / beta"
