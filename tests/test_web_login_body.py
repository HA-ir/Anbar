"""Loop #6 audit tests (B-052: non-object JSON to /ui/login)."""

from __future__ import annotations


def test_login_non_object_json_400(client):
    """B-052: a JSON array/scalar body must give 400, not 500."""
    for payload in ("[1,2,3]", '"a string"', "42", "null", "true"):
        r = client.post(
            "/ui/login",
            content=payload,
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 400, f"{payload} → {r.status_code}"
        assert r.json()["detail"] == "expected JSON {key}"


def test_login_valid_body_still_works(client):
    r = client.post("/ui/login", json={"key": "test-admin-key"})
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


def test_login_wrong_key_401(client):
    r = client.post("/ui/login", json={"key": "nope"})
    assert r.status_code == 401
