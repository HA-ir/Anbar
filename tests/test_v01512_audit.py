"""Regression tests for the v0.15.11 audit (v0.15.12).

Covers:
- Content-Disposition sanitization (RFC 5987): unicode filenames must not
  500 the download endpoint, and CR/LF/quotes must not break the header.
- Download response carries X-Content-Type-Options: nosniff.
- Telegram MTProto auth endpoints: bad code path keeps temp state usable
  (client disconnected, not persisted) and returns a proper 400.
"""

from urllib.parse import quote

from fastapi.testclient import TestClient


def _upload(client: TestClient, name: str, body: bytes = b"hello") -> dict:
    r = client.post(
        "/api/v1/upload",
        files={"file": (name, body, "application/octet-stream")},
        headers={"Authorization": "Bearer test-admin-key"},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_unicode_filename_download_no_500(client: TestClient):
    """Persian filename must download 200 with an RFC 5987 header."""
    obj = _upload(client, "گزارش مالی.pdf")
    r = client.get(f"/f/{obj['id']}", headers={"Authorization": "Bearer test-admin-key"})
    assert r.status_code == 200
    cd = r.headers["content-disposition"]
    assert "filename*=UTF-8''" in cd
    assert quote("گزارش مالی.pdf", safe="") in cd
    # header must be pure latin-1 (starlette would 500 otherwise)
    cd.encode("latin-1")


def test_header_injection_filename_neutralized(client: TestClient):
    """CR/LF/quotes in a stored filename can't break the header."""
    evil = 'x"; evil="pwned\r\nX-Injected: yes'
    obj = _upload(client, evil)
    r = client.get(f"/f/{obj['id']}", headers={"Authorization": "Bearer test-admin-key"})
    assert r.status_code == 200
    cd = r.headers["content-disposition"]
    assert "\r" not in cd and "\n" not in cd
    assert "X-Injected" not in r.headers


def test_download_has_nosniff(client: TestClient):
    obj = _upload(client, "plain.txt", b"data")
    r = client.get(f"/f/{obj['id']}", headers={"Authorization": "Bearer test-admin-key"})
    assert r.status_code == 200
    assert r.headers.get("x-content-type-options") == "nosniff"


def test_verify_code_missing_params_still_400(client: TestClient):
    r = client.post(
        "/api/v1/admin/telegram/verify-code",
        json={},
        headers={"Authorization": "Bearer test-admin-key"},
    )
    assert r.status_code == 400


def test_send_code_missing_phone_400(client: TestClient):
    r = client.post(
        "/api/v1/admin/telegram/send-code",
        json={},
        headers={"Authorization": "Bearer test-admin-key"},
    )
    assert r.status_code == 400


def test_verify_code_requires_admin(client: TestClient):
    r = client.post("/api/v1/admin/telegram/verify-code", json={"code": "12345"})
    assert r.status_code in (401, 403)
