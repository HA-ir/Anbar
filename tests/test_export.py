"""v0.9.3: metadata export endpoint."""
from __future__ import annotations

import io

ADMIN = {"Authorization": "Bearer test-admin-key"}


def test_export_json_and_csv(client):
    r = client.post("/api/v1/upload", headers=ADMIN,
                    files={"file": ("x.bin", io.BytesIO(b"data"), "application/octet-stream")})
    assert r.status_code == 200
    j = client.get("/api/v1/admin/export", headers=ADMIN)
    assert j.status_code == 200
    body = j.json()
    assert body["exported"] >= 1
    c = client.get("/api/v1/admin/export?format=csv", headers=ADMIN)
    assert "anbar-objects.csv" in c.headers["content-disposition"]
    assert "id,filename,size" in c.text.splitlines()[0]
    # no admin key → 401/403
    anon = client.get("/api/v1/admin/export")
    assert anon.status_code in (401, 403)
