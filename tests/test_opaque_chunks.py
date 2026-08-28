from __future__ import annotations

import io
import re

from starlette.testclient import TestClient

from anbar.objects import opaque_chunk_name

ADMIN = {"Authorization": "Bearer test-admin-key"}


def test_opaque_chunk_name_format():
    name1 = opaque_chunk_name(0)
    name2 = opaque_chunk_name(1)
    assert name1 != name2
    assert re.match(r"^blob_[0-9a-f]{32}_0000\.bin$", name1)
    assert re.match(r"^blob_[0-9a-f]{32}_0001\.bin$", name2)


def test_upload_chunk_names_are_opaque(client: TestClient):
    client.post("/ui/login", json={"key": "test-admin-key"})

    file_bytes = b"SECRET DATA CONTENT " * 100
    files = {"file": ("my_classified_document.pdf", io.BytesIO(file_bytes), "application/pdf")}

    r = client.post("/api/v1/upload", files=files, headers=ADMIN)
    assert r.status_code == 200
    obj_id = r.json()["id"]

    # Verify download serves original filename
    dl_r = client.get(f"/f/{obj_id}", headers=ADMIN)
    assert dl_r.status_code == 200
    assert "my_classified_document.pdf" in dl_r.headers.get("content-disposition", "")
    assert dl_r.content == file_bytes
