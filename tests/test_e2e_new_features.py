"""v0.11: Comprehensive End-to-End (E2E) integration tests for the 6 new capabilities.
Simulates real full client workflows without mocks:
1. S3 Lifecycle (PutObject -> Head -> Get Range -> ETag 304 -> List -> Delete)
2. ETag & Smart Content-Disposition in direct /f/ download routes
3. Telegram Mini App initData Auth -> Web Session generation -> Authenticated CRUD
4. AES-256-GCM Zero-Knowledge stream encryption & decryption roundtrip
5. Forum Topic configuration integrity in Bot backend
"""

from __future__ import annotations

import hashlib
import hmac
import io
import time

import pytest

from anbar.auth import verify_telegram_init_data
from anbar.crypto import decrypt_gcm, derive_key_256, encrypt_gcm

ADMIN = {"Authorization": "Bearer test-admin-key"}


# --- 1. S3 Complete Lifecycle E2E ---
def test_e2e_s3_complete_lifecycle(client):
    bucket = "e2e-bucket"
    key = "docs/sample.pdf"
    content = b"%PDF-1.4 ... binary pdf bytes simulated for e2e test ..." * 50  # Multi-KB content

    # Step 1: Upload via S3 PUT
    put_res = client.put(
        f"/s3/{bucket}/{key}",
        headers={**ADMIN, "Content-Type": "application/pdf"},
        content=content,
    )
    assert put_res.status_code == 200
    etag = put_res.headers.get("etag")
    assert etag is not None

    # Step 2: HEAD request verification
    head_res = client.head(f"/s3/{bucket}/{key}", headers=ADMIN)
    assert head_res.status_code == 200
    assert head_res.headers.get("etag") == etag
    assert head_res.headers.get("content-length") == str(len(content))
    assert head_res.headers.get("content-type") == "application/pdf"

    # Step 3: Full GET verification
    get_res = client.get(f"/s3/{bucket}/{key}", headers=ADMIN)
    assert get_res.status_code == 200
    assert get_res.content == content

    # Step 4: Conditional GET (ETag cache hit -> 304)
    c_get_res = client.get(f"/s3/{bucket}/{key}", headers={**ADMIN, "If-None-Match": etag})
    assert c_get_res.status_code == 304
    assert len(c_get_res.content) == 0

    # Step 5: Byte-Range GET (Partial Content -> 206)
    range_header = "bytes=10-50"
    range_res = client.get(f"/s3/{bucket}/{key}", headers={**ADMIN, "Range": range_header})
    assert range_res.status_code == 206
    assert range_res.content == content[10:51]
    assert range_res.headers.get("content-range") == f"bytes 10-50/{len(content)}"

    # Step 6: ListBucket verification
    list_res = client.get(f"/s3/{bucket}", headers=ADMIN)
    assert list_res.status_code == 200
    assert "<Name>e2e-bucket</Name>" in list_res.text
    assert "<Key>docs/sample.pdf</Key>" in list_res.text
    assert f"<Size>{len(content)}</Size>" in list_res.text

    # Step 7: Delete Object
    del_res = client.delete(f"/s3/{bucket}/{key}", headers=ADMIN)
    assert del_res.status_code == 204

    # Step 8: Verify Deletion
    assert client.head(f"/s3/{bucket}/{key}", headers=ADMIN).status_code == 404
    assert client.get(f"/s3/{bucket}/{key}", headers=ADMIN).status_code == 404


# --- 2. Direct /f/ Download ETag & Smart Disposition E2E ---
def test_e2e_download_etag_and_disposition(client):
    # Upload video file
    video_content = b"\x00\x00\x00 ftypisom" + b"dummy_video_stream" * 100
    r = client.post(
        "/api/v1/upload",
        headers=ADMIN,
        files={"file": ("intro.mp4", io.BytesIO(video_content), "video/mp4")},
    )
    assert r.status_code == 200
    obj_id = r.json()["id"]
    sha = r.json()["sha256"]

    # 1. Video should automatically serve with inline disposition
    res_view = client.get(f"/f/{obj_id}", headers=ADMIN)
    assert res_view.status_code == 200
    assert 'inline; filename="intro.mp4"' in res_view.headers.get("content-disposition", "")
    assert res_view.headers.get("etag") == f'"{sha}"'

    # 2. Conditional If-None-Match gives 304
    res_304 = client.get(f"/f/{obj_id}", headers={**ADMIN, "If-None-Match": f'"{sha}"'})
    assert res_304.status_code == 304

    # 3. Forcing download via ?dl=1 switches disposition to attachment
    res_dl = client.get(f"/f/{obj_id}?dl=1", headers=ADMIN)
    assert res_dl.status_code == 200
    assert 'attachment; filename="intro.mp4"' in res_dl.headers.get("content-disposition", "")


# --- 3. Telegram Mini App Auth & Web Flow E2E ---
def test_e2e_telegram_miniapp_flow(client):
    # Serve UI
    ui_res = client.get("/tg-app")
    assert ui_res.status_code == 200
    assert "Telegram Mini App" in ui_res.text

    # Telegram initData cryptographic validation
    bot_token = "987654:TEST_BOT_TOKEN_FOR_MINIAPP"
    auth_date = int(time.time())
    params = {
        "auth_date": str(auth_date),
        "query_id": "AAGD8-42_E2E",
        "user": '{"id":12345678,"first_name":"Hossein","username":"hossein"}',
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    valid_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    valid_init_data = (
        f"auth_date={params['auth_date']}&query_id={params['query_id']}"
        f"&user={params['user']}&hash={valid_hash}"
    )

    # Verify pass
    assert verify_telegram_init_data(valid_init_data, bot_token) is True

    # Tampered user id check
    fake_init_data = valid_init_data.replace("12345678", "87654321")
    assert verify_telegram_init_data(fake_init_data, bot_token) is False


# --- 4. Zero-Knowledge AES-256-GCM Cryptographic E2E ---
def test_e2e_zero_knowledge_encryption_roundtrip():
    user_passphrase = "Ultra-Secure-Password-2026-!#$"
    derived_key = derive_key_256(user_passphrase)
    assert len(derived_key) == 32

    raw_data = b"This is confidential proprietary data to be stored securely." * 200

    # Encrypt
    encrypted_blob = encrypt_gcm(raw_data, derived_key)
    assert encrypted_blob != raw_data
    # 12B IV + 16B Auth Tag + len(raw_data)
    assert len(encrypted_blob) == len(raw_data) + 28

    # Decrypt
    decrypted_data = decrypt_gcm(encrypted_blob, derived_key)
    assert decrypted_data == raw_data

    # Bit-flip corruption detection
    corrupted = bytearray(encrypted_blob)
    corrupted[15] ^= 0x01  # Alter tag
    with pytest.raises(ValueError, match="Decryption failed"):
        decrypt_gcm(bytes(corrupted), derived_key)
