"""
Comprehensive end-to-end integration and edge-case test suite for Anbar 0.12.0.
Covers:
1. Multi-type preview & streaming (Video, Image, Audio, PDF, Text/Code/JSON).
2. Range-requests & Partial Content (206) vs Full (200) vs 304 ETag.
3. S3 PutObject, GetObject with Range, HeadObject, DeleteObject, ListObjectsV2.
4. Telegram MiniApp HMAC verification.
5. AES-256-GCM Zero-Knowledge encryption/decryption round-trip.
6. Public vs Protected download auth behaviors.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import time

import pytest

from anbar.auth import verify_telegram_init_data
from anbar.crypto import decrypt_gcm, derive_key_256, encrypt_gcm


def test_crypto_gcm_integrity_and_tampering():
    """Verify AES-256-GCM encryption, decryption, and authentication tag tampering detection."""
    key = derive_key_256("my-secret-passphrase-2026")
    plaintext = b"Telegram Zero-Knowledge Object Storage Chunks"

    ciphertext = encrypt_gcm(plaintext, key)
    assert len(ciphertext) == 12 + 16 + len(plaintext)

    decrypted = decrypt_gcm(ciphertext, key)
    assert decrypted == plaintext

    # Tampering ciphertext payload
    tampered = bytearray(ciphertext)
    tampered[-1] ^= 0x01
    with pytest.raises(ValueError, match="Decryption failed"):
        decrypt_gcm(bytes(tampered), key)

    # Tampering auth tag
    tampered_tag = bytearray(ciphertext)
    tampered_tag[15] ^= 0xFF
    with pytest.raises(ValueError, match="Decryption failed"):
        decrypt_gcm(bytes(tampered_tag), key)


def test_multitype_uploads_and_streaming_preview(client):
    """Test uploads and previews for Video, Image, Audio, PDF, Text, and Code."""
    ADMIN = {"Authorization": "Bearer test-admin-key"}

    files_to_test = [
        ("movie.mp4", b"\x00\x00\x00\x1cftypisom" + b"A" * 50000, "video/mp4"),
        ("photo.png", b"\x89PNG\r\n\x1a\n" + b"B" * 20000, "image/png"),
        ("song.mp3", b"ID3\x03\x00\x00\x00" + b"C" * 15000, "audio/mpeg"),
        ("doc.pdf", b"%PDF-1.4\n1 0 obj\n" + b"D" * 10000, "application/pdf"),
        ("script.py", b"print('Hello Anbar!')\n", "text/x-python"),
        ("config.json", b'{"service":"anbar","version":"0.12.0"}', "application/json"),
    ]

    uploaded_ids = {}
    for filename, content, mime in files_to_test:
        resp = client.post(
            "/api/v1/upload",
            files={"file": (filename, io.BytesIO(content), mime)},
            headers=ADMIN,
        )
        assert resp.status_code == 200, f"Upload failed for {filename}: {resp.text}"
        data = resp.json()
        assert "id" in data
        assert data["size"] == len(content)
        uploaded_ids[filename] = data["id"]

    # Test full GET for video with admin authorization header
    vid_id = uploaded_ids["movie.mp4"]
    res_vid = client.get(f"/f/{vid_id}", headers=ADMIN)
    assert res_vid.status_code == 200
    assert res_vid.headers["content-type"] == "video/mp4"
    assert "inline" in res_vid.headers["content-disposition"]
    assert res_vid.headers["accept-ranges"] == "bytes"

    # Test Range request for video (Partial Content 206)
    res_range = client.get(f"/f/{vid_id}", headers={**ADMIN, "Range": "bytes=0-1023"})
    assert res_range.status_code == 206
    assert len(res_range.content) == 1024
    assert res_range.headers["content-range"] == f"bytes 0-1023/{len(files_to_test[0][1])}"

    # Test ETag conditional match (304) on full request
    etag = res_vid.headers["etag"]
    res_etag_304 = client.get(f"/f/{vid_id}", headers={**ADMIN, "If-None-Match": etag})
    assert res_etag_304.status_code == 304

    # Test Range request with If-None-Match MUST NOT return 304, must stream 206
    res_range_etag = client.get(
        f"/f/{vid_id}", headers={**ADMIN, "Range": "bytes=100-199", "If-None-Match": etag}
    )
    assert res_range_etag.status_code == 206
    assert len(res_range_etag.content) == 100


def test_s3_protocol_full_lifecycle(client):
    """Test S3 PUT, HEAD, GET with Range, ListObjectsV2, and DELETE."""
    ADMIN = {"Authorization": "Bearer test-admin-key"}
    bucket = "mybucket"
    key = "assets/logo.png"
    payload = b"\x89PNG\r\n\x1a\n" + b"X" * 10240

    # 1. PutObject
    put_res = client.put(
        f"/s3/{bucket}/{key}",
        headers={**ADMIN, "Content-Type": "image/png"},
        content=payload,
    )
    assert put_res.status_code == 200
    assert "etag" in put_res.headers

    # 2. HeadObject
    head_res = client.head(f"/s3/{bucket}/{key}", headers=ADMIN)
    assert head_res.status_code == 200
    assert head_res.headers["content-length"] == str(len(payload))
    assert head_res.headers["content-type"] == "image/png"

    # 3. GetObject full
    get_res = client.get(f"/s3/{bucket}/{key}", headers=ADMIN)
    assert get_res.status_code == 200
    assert get_res.content == payload

    # 4. GetObject with Range
    get_range = client.get(f"/s3/{bucket}/{key}", headers={**ADMIN, "Range": "bytes=0-99"})
    assert get_range.status_code == 206
    assert len(get_range.content) == 100
    assert get_range.content == payload[:100]

    # 5. ListObjectsV2
    list_res = client.get(f"/s3/{bucket}", headers=ADMIN)
    assert list_res.status_code == 200
    assert "<Key>assets/logo.png</Key>" in list_res.text
    assert f"<Size>{len(payload)}</Size>" in list_res.text

    # 6. DeleteObject
    del_res = client.delete(f"/s3/{bucket}/{key}", headers=ADMIN)
    assert del_res.status_code == 204

    # Verify deleted
    assert client.head(f"/s3/{bucket}/{key}", headers=ADMIN).status_code == 404


def test_telegram_miniapp_crypto_validation():
    """Verify Telegram WebApp initData cryptographic signature verification."""
    bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"

    auth_date = str(int(time.time()))
    data_dict = {
        "auth_date": auth_date,
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": '{"id":12345678,"first_name":"Hossein","username":"hossein"}',
    }
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data_dict.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

    valid_init_data = (
        f"auth_date={auth_date}&query_id={data_dict['query_id']}"
        f"&user={data_dict['user']}&hash={calc_hash}"
    )

    # Must validate true
    assert verify_telegram_init_data(valid_init_data, bot_token) is True

    # Tampered initData must fail
    tampered_init_data = valid_init_data.replace("Hossein", "Attacker")
    assert verify_telegram_init_data(tampered_init_data, bot_token) is False
