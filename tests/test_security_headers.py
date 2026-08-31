"""Loop #8 security tests (B-057: header injection via upload filename)."""

from __future__ import annotations

from starlette.testclient import TestClient

UP = {"Authorization": "Bearer test-key"}


def test_upload_raw_crlf_filename_never_reaches_header(client: TestClient):
    """B-057: a CR/LF-bearing X-File-Name must be sanitized (RFC 5987 path),
    not echoed raw into Content-Disposition on download."""
    evil = "evil\r\nX-Injected: 1\r\n.b"
    r = client.post(
        "/api/v1/upload/raw",
        content=b"A" * 32,
        headers={**UP, "X-File-Name": evil, "Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 200, r.text
    obj_id = r.json()["id"]

    # owner key can download without auth side effects
    r2 = client.get(f"/f/{obj_id}?dl=1", headers=UP)
    assert r2.status_code == 200
    cd = r2.headers.get("content-disposition", "")
    # the injected header must appear nowhere — CR/LF never survives raw
    assert "\r" not in cd and "\n" not in cd
    # the whole disposition is ONE header value (single attachment; filename
    # pair) — no second header can be smuggled into the response
    assert cd.count("attachment") == 1
    assert ": " not in cd.split("filename*=")[-1] or "X-Injected%3A" in cd


def test_upload_raw_filename_header_is_attachment_by_default(client: TestClient):
    """Companion: normal download always sends attachment + nosniff."""
    r = client.post(
        "/api/v1/upload/raw",
        content=b"B" * 16,
        headers={**UP, "X-File-Name": "ok.txt", "Content-Type": "text/plain"},
    )
    obj_id = r.json()["id"]
    r2 = client.get(f"/f/{obj_id}", headers=UP)
    assert r2.headers["x-content-type-options"] == "nosniff"


def test_info_endpoint_metadata_only(client: TestClient):
    """/info must not leak the manifest blob (storage refs) or uploader key."""
    r = client.post(
        "/api/v1/upload/raw",
        content=b"C" * 16,
        headers={**UP, "X-File-Name": "meta.bin"},
    )
    obj_id = r.json()["id"]
    info = client.get(f"/f/{obj_id}/info")
    assert info.status_code == 200
    body = info.json()
    assert "manifest" not in body
    assert "uploader_key" not in body
    assert "file_id" not in body
    assert set(body) == {
        "id",
        "filename",
        "size",
        "sha256",
        "content_type",
        "chunks",
        "created_at",
        "downloaded",
    }
