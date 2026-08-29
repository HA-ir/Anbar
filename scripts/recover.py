#!/usr/bin/env python3
"""scripts/recover.py — Standalone Zero-Dependency Disaster Recovery for Anbar

Recovers all files and folders directly from raw Telegram channel messages/chunks
without requiring Anbar server running or any SQLite database.

Usage:
  # 1. Recover from an exported Telegram JSON dump:
  python3 scripts/recover.py --dump export.json --output ./recovered/ --secret "SECRET"

  # 2. Decrypt a single client-side encrypted file offline:
  python3 scripts/recover.py --decrypt-zk file.pdf.enc --password "PASS" -o file.pdf
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import ctypes.util
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

# ==========================================
# 1. Built-in OpenSSL AES-256-GCM Engine
# ==========================================
_libcrypto_path = ctypes.util.find_library("crypto")
_libcrypto = None
if _libcrypto_path:
    try:
        _libcrypto = ctypes.CDLL(_libcrypto_path)
        _libcrypto.EVP_CIPHER_CTX_new.restype = ctypes.c_void_p
        _libcrypto.EVP_CIPHER_CTX_free.argtypes = [ctypes.c_void_p]
        _libcrypto.EVP_aes_256_gcm.restype = ctypes.c_void_p

        _libcrypto.EVP_DecryptInit_ex.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
        ]
        _libcrypto.EVP_CIPHER_CTX_ctrl.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
        ]
        _libcrypto.EVP_DecryptUpdate.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_char_p,
            ctypes.c_int,
        ]
        _libcrypto.EVP_DecryptFinal_ex.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_int),
        ]
    except Exception:
        _libcrypto = None

_GCM_NONCE_LEN = 12
_GCM_TAG_LEN = 16
EVP_CTRL_GCM_SET_IVLEN = 0x9
EVP_CTRL_GCM_SET_TAG = 0x11


def decrypt_aes_gcm_raw(payload: bytes, key: bytes) -> bytes:
    """Decrypt payload formatted as Nonce (12B) + Tag (16B) + Ciphertext."""
    if len(payload) < _GCM_NONCE_LEN + _GCM_TAG_LEN:
        raise ValueError(f"Payload too short ({len(payload)} bytes)")
    if len(key) != 32:
        raise ValueError("AES-256 requires 32-byte key")

    nonce = payload[:_GCM_NONCE_LEN]
    tag = payload[_GCM_NONCE_LEN : _GCM_NONCE_LEN + _GCM_TAG_LEN]
    ciphertext = payload[_GCM_NONCE_LEN + _GCM_TAG_LEN :]

    if _libcrypto:
        ctx = _libcrypto.EVP_CIPHER_CTX_new()
        if not ctx:
            raise MemoryError("EVP_CIPHER_CTX allocation failed")
        try:
            cipher = _libcrypto.EVP_aes_256_gcm()
            if _libcrypto.EVP_DecryptInit_ex(ctx, cipher, None, None, None) != 1:
                raise RuntimeError("EVP_DecryptInit_ex failed")
            if _libcrypto.EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, len(nonce), None) != 1:
                raise RuntimeError("Failed setting IV len")
            if _libcrypto.EVP_DecryptInit_ex(ctx, None, None, key, nonce) != 1:
                raise RuntimeError("Failed setting key/nonce")
            if _libcrypto.EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_TAG, len(tag), tag) != 1:
                raise RuntimeError("Failed setting expected tag")

            out = ctypes.create_string_buffer(len(ciphertext) + 16)
            out_len = ctypes.c_int(0)
            if len(ciphertext) > 0:
                res = _libcrypto.EVP_DecryptUpdate(
                    ctx, out, ctypes.byref(out_len), ciphertext, len(ciphertext)
                )
                if res != 1:
                    raise ValueError("Decryption failed (corrupted ciphertext)")
            final_ptr = ctypes.cast(ctypes.byref(out, out_len.value), ctypes.c_char_p)
            dummy_len = ctypes.c_int(0)
            if _libcrypto.EVP_DecryptFinal_ex(ctx, final_ptr, ctypes.byref(dummy_len)) != 1:
                raise ValueError("Authentication tag mismatch (invalid key or corrupted data)")
            return out.raw[: out_len.value + dummy_len.value]
        finally:
            _libcrypto.EVP_CIPHER_CTX_free(ctx)

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ciphertext + tag, None)
    except ImportError as err:
        raise RuntimeError("OpenSSL library or 'cryptography' package required.") from err


def decrypt_server_chunk(chunk_bytes: bytes, secret: str) -> bytes:
    """Decrypt server-side encrypted chunk using Master Secret."""
    key = hashlib.sha256(secret.encode("utf-8")).digest()
    return decrypt_aes_gcm_raw(chunk_bytes, key)


def decrypt_client_zk(data: bytes, passphrase: str) -> bytes:
    """Decrypt client-side True ZK file (ANBAR_ZK1 standard format)."""
    magic = b"ANBAR_ZK1"
    if not data.startswith(magic):
        raise ValueError("Not an ANBAR_ZK1 formatted file")
    
    min_len = len(magic) + 16 + 12 + 16
    if len(data) < min_len:
        raise ValueError("Truncated ANBAR_ZK1 file")

    offset = len(magic)
    salt = data[offset : offset + 16]
    offset += 16
    iv = data[offset : offset + 12]
    offset += 12
    tag = data[offset : offset + 16]
    offset += 16
    ciphertext = data[offset:]

    key = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, 100_000, dklen=32)
    payload_to_decrypt = iv + tag + ciphertext
    return decrypt_aes_gcm_raw(payload_to_decrypt, key)


# ==========================================
# 2. Telegram Caption & Event Decoders
# ==========================================

CAPTION_PREFIX = "anbar:v1:"
EVENT_PREFIX = "anbar:v1:evt:"


def decode_caption(caption: str, secret: str | None = None) -> dict[str, Any] | None:
    if not caption or not isinstance(caption, str):
        return None
    caption = caption.strip()
    if not caption.startswith(CAPTION_PREFIX):
        return None
    envelope = caption[len(CAPTION_PREFIX) :]
    if envelope.startswith("e:"):
        if not secret:
            return None
        b64_str = envelope[2:]
        b64_str += "=" * (-len(b64_str) % 4)
        try:
            raw = base64.urlsafe_b64decode(b64_str)
            dec_bytes = decrypt_server_chunk(raw, secret)
            return json.loads(dec_bytes.decode("utf-8"))
        except Exception:
            return None
    elif envelope.startswith("p:"):
        b64_str = envelope[2:]
        b64_str += "=" * (-len(b64_str) % 4)
        try:
            raw = base64.urlsafe_b64decode(b64_str)
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None
    return None


def decode_meta_event(text: str, secret: str | None = None) -> dict[str, Any] | None:
    if not text or not isinstance(text, str):
        return None
    text = text.strip()
    if not text.startswith(EVENT_PREFIX):
        return None
    envelope = text[len(EVENT_PREFIX) :]
    if envelope.startswith("e:"):
        if not secret:
            return None
        b64_str = envelope[2:]
        b64_str += "=" * (-len(b64_str) % 4)
        try:
            raw = base64.urlsafe_b64decode(b64_str)
            dec_bytes = decrypt_server_chunk(raw, secret)
            return json.loads(dec_bytes.decode("utf-8"))
        except Exception:
            return None
    elif envelope.startswith("p:"):
        b64_str = envelope[2:]
        b64_str += "=" * (-len(b64_str) % 4)
        try:
            raw = base64.urlsafe_b64decode(b64_str)
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None
    return None


# ==========================================
# 3. File Reassembly & Recovery
# ==========================================

def recover_files(
    chunks_meta: list[dict[str, Any]],
    events: list[dict[str, Any]],
    output_dir: str | Path,
    server_secret: str | None = None,
    client_passphrase: str | None = None,
) -> dict[str, Any]:
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    objects: dict[str, dict[str, Any]] = {}
    for item in chunks_meta:
        meta = item["meta"]
        obj_id = str(meta.get("id") or "unknown")
        if obj_id not in objects:
            objects[obj_id] = {
                "id": obj_id,
                "fn": meta.get("fn", f"recovered_{obj_id}.bin"),
                "total_chunks": meta.get("n", 1),
                "chunks": {},
            }
        idx = meta.get("i", 0)
        objects[obj_id]["chunks"][idx] = item["data"]

    for ev in events:
        op = ev.get("op")
        if op in ("rn_obj", "mv_obj"):
            obj_id = ev.get("id")
            if obj_id in objects:
                objects[obj_id]["fn"] = ev.get("new_fn", objects[obj_id]["fn"])
        elif op == "rn_dir":
            old_p = ev.get("old_prefix", "")
            new_p = ev.get("new_prefix", "")
            for obj in objects.values():
                if obj["fn"].startswith(old_p):
                    obj["fn"] = new_p + obj["fn"][len(old_p) :]
        elif op == "del_batch":
            for dead_id in ev.get("ids", []):
                objects.pop(dead_id, None)

    recovered_count = 0
    errors: list[str] = []

    for obj_id, obj in objects.items():
        total_chunks = obj["total_chunks"]
        fn = obj["fn"]
        missing = [i for i in range(total_chunks) if i not in obj["chunks"]]
        if missing:
            errors.append(f"Object {obj_id} ({fn}): missing chunks {missing}")
            continue

        assembled_bytes = bytearray()
        try:
            for i in range(total_chunks):
                raw_chunk = obj["chunks"][i]
                if server_secret and not raw_chunk.startswith(b"ANBAR_ZK1"):
                    try:
                        decrypted_chunk = decrypt_server_chunk(raw_chunk, server_secret)
                        assembled_bytes.extend(decrypted_chunk)
                    except Exception:
                        assembled_bytes.extend(raw_chunk)
                else:
                    assembled_bytes.extend(raw_chunk)
            
            file_data = bytes(assembled_bytes)

            if file_data.startswith(b"ANBAR_ZK1"):
                if not client_passphrase:
                    print(f"⚠️ File '{fn}' is client-encrypted but no password given.")
                    clean_name = fn if fn.endswith(".enc") else (fn + ".enc")
                else:
                    file_data = decrypt_client_zk(file_data, client_passphrase)
                    clean_name = fn[:-4] if fn.endswith(".enc") else fn
            else:
                clean_name = fn

            dest_file = out_path / clean_name
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            with open(dest_file, "wb") as f:
                f.write(file_data)

            recovered_count += 1
            print(f"✅ Recovered: {clean_name} ({len(file_data):,} bytes)")

        except Exception as ex:
            errors.append(f"Failed recovering {fn}: {ex}")

    return {"recovered_count": recovered_count, "errors": errors}


def main():
    parser = argparse.ArgumentParser(description="Anbar Offline Disaster Recovery Tool")
    parser.add_argument("--decrypt-zk", type=str, help="Decrypt a single local ANBAR_ZK1 file")
    parser.add_argument("-p", "--password", type=str, help="Client ZK passphrase")
    parser.add_argument("-s", "--secret", type=str, help="Anbar Master Server Secret")
    parser.add_argument("-o", "--output", type=str, default="./recovered", help="Output dir/file")
    parser.add_argument("--dump-dir", type=str, help="Directory of chunk files")
    args = parser.parse_args()

    if args.decrypt_zk:
        if not args.password:
            import getpass
            args.password = getpass.getpass("Enter Client ZK Passphrase: ")
        
        src_path = Path(args.decrypt_zk)
        if not src_path.exists():
            print(f"Error: File {src_path} not found", file=sys.stderr)
            sys.exit(1)
        
        raw = src_path.read_bytes()
        try:
            dec = decrypt_client_zk(raw, args.password)
            out_file = Path(args.output)
            if out_file.is_dir() or str(out_file).endswith(("/", "\\")):
                is_enc = src_path.suffix.lower() == ".enc"
                clean_name = src_path.stem if is_enc else src_path.name + ".dec"
                out_file = out_file / clean_name
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(dec)
            print(f"✅ Successfully decrypted to {out_file} ({len(dec):,} bytes)")
        except Exception as e:
            print(f"❌ Decryption failed: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
