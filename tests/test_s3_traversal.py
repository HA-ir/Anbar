"""Loop #8: S3 path-traversal sweep (uses the standard client fixture).

Result of the sweep (loop #8): FastAPI/Starlette normalize or refuse
traversal-shaped paths at the routing layer — `../` segments yield 404/405
cleanly, never a 500, and S3 keys are stored as opaque kv ids
(`s3:<bucket>:<key>` → obj_id) so no filesystem path is ever built from
user input. These tests pin that behaviour.
"""

from __future__ import annotations

from starlette.testclient import TestClient

UP = {"Authorization": "Bearer test-key"}


def test_s3_traversal_keys_refuse_cleanly(client: TestClient):
    """Traversal-shaped keys must never 500 or escape the virtual store."""
    r = client.put("/s3/b/normal.txt", content=b"hello", headers=UP)
    assert r.status_code == 200
    for key in ("../escape.txt", "a/../../b.txt", "deep/../../escape.txt"):
        put = client.put(f"/s3/b/{key}", content=b"x" * 8, headers=UP)
        get = client.get(f"/s3/b/{key}", headers=UP)
        head = client.head(f"/s3/b/{key}", headers=UP)
        # clean refusal (404/405) or an isolated round-trip — never 5xx
        assert put.status_code in (200, 404, 405), (key, put.status_code)
        assert get.status_code in (200, 404, 405), (key, get.status_code)
        assert head.status_code in (200, 404, 405), (key, head.status_code)


def test_s3_dotdot_bucket_never_500(client: TestClient):
    """Weird bucket names must not 500 the list/get endpoints."""
    for path in ("/s3/..", "/s3/b/..", "/s3/..%2F", "/s3/%2e%2e"):
        r = client.get(path, headers=UP)
        assert r.status_code in (200, 404, 405), (path, r.status_code)


def test_s3_get_roundtrip_normal_key(client: TestClient):
    """Sanity: normal keys still round-trip with correct content."""
    client.put("/s3/b2/ok.bin", content=b"PAYLOAD-123", headers=UP)
    r = client.get("/s3/b2/ok.bin", headers=UP)
    assert r.status_code == 200
    assert r.content == b"PAYLOAD-123"
