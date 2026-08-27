"""v0.11: Zero-knowledge AES-256-GCM encryption / decryption for chunks.
Uses OpenSSL libcrypto via ctypes without requiring external pip dependencies.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import hashlib
import os

_libcrypto_path = ctypes.util.find_library("crypto")
_libcrypto = None
if _libcrypto_path:
    try:
        _libcrypto = ctypes.CDLL(_libcrypto_path)
        _libcrypto.EVP_CIPHER_CTX_new.restype = ctypes.c_void_p
        _libcrypto.EVP_CIPHER_CTX_free.argtypes = [ctypes.c_void_p]
        _libcrypto.EVP_aes_256_gcm.restype = ctypes.c_void_p

        _libcrypto.EVP_EncryptInit_ex.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
        ]
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
        _libcrypto.EVP_EncryptUpdate.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_char_p,
            ctypes.c_int,
        ]
        _libcrypto.EVP_DecryptUpdate.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_char_p,
            ctypes.c_int,
        ]
        _libcrypto.EVP_EncryptFinal_ex.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_int),
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
EVP_CTRL_GCM_GET_TAG = 0x10
EVP_CTRL_GCM_SET_TAG = 0x11


def derive_key_256(secret: str | bytes) -> bytes:
    """Derive 32-byte (256-bit) AES key from arbitrary string/bytes using SHA-256."""
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    return hashlib.sha256(secret).digest()


def encrypt_gcm(data: bytes, key: bytes, nonce: bytes | None = None) -> bytes:
    """
    Encrypt bytes using AES-256-GCM.
    Returns: nonce (12B) + tag (16B) + ciphertext
    """
    if len(key) != 32:
        raise ValueError("AES-256 requires a 32-byte key")

    if nonce is None:
        nonce = os.urandom(_GCM_NONCE_LEN)
    elif len(nonce) != _GCM_NONCE_LEN:
        raise ValueError("GCM nonce must be 12 bytes")

    if _libcrypto is None:
        raise RuntimeError("OpenSSL libcrypto unavailable for AES-GCM encryption")

    ctx = _libcrypto.EVP_CIPHER_CTX_new()
    if not ctx:
        raise MemoryError("Failed to allocate EVP_CIPHER_CTX")
    try:
        cipher = _libcrypto.EVP_aes_256_gcm()
        if _libcrypto.EVP_EncryptInit_ex(ctx, cipher, None, None, None) != 1:
            raise RuntimeError("EVP_EncryptInit_ex failed")

        if _libcrypto.EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, len(nonce), None) != 1:
            raise RuntimeError("Failed to set IV length")

        if _libcrypto.EVP_EncryptInit_ex(ctx, None, None, key, nonce) != 1:
            raise RuntimeError("Failed to set key and nonce")

        out = ctypes.create_string_buffer(len(data) + 16)
        out_len = ctypes.c_int(0)

        if _libcrypto.EVP_EncryptUpdate(ctx, out, ctypes.byref(out_len), data, len(data)) != 1:
            raise RuntimeError("EVP_EncryptUpdate failed")

        dummy_len = ctypes.c_int(0)
        final_ptr = ctypes.cast(ctypes.byref(out, out_len.value), ctypes.c_char_p)
        if _libcrypto.EVP_EncryptFinal_ex(ctx, final_ptr, ctypes.byref(dummy_len)) != 1:
            raise RuntimeError("EVP_EncryptFinal_ex failed")

        tag = ctypes.create_string_buffer(_GCM_TAG_LEN)
        if _libcrypto.EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_GET_TAG, _GCM_TAG_LEN, tag) != 1:
            raise RuntimeError("Failed to get GCM tag")

        return nonce + tag.raw[:_GCM_TAG_LEN] + out.raw[: out_len.value]
    finally:
        _libcrypto.EVP_CIPHER_CTX_free(ctx)


def decrypt_gcm(encrypted_data: bytes, key: bytes) -> bytes:
    """
    Decrypt bytes produced by encrypt_gcm (nonce + tag + ciphertext).
    """
    if len(key) != 32:
        raise ValueError("AES-256 requires a 32-byte key")

    if len(encrypted_data) < _GCM_NONCE_LEN + _GCM_TAG_LEN:
        raise ValueError("Ciphertext too short")

    nonce = encrypted_data[:_GCM_NONCE_LEN]
    tag = encrypted_data[_GCM_NONCE_LEN : _GCM_NONCE_LEN + _GCM_TAG_LEN]
    ciphertext = encrypted_data[_GCM_NONCE_LEN + _GCM_TAG_LEN :]

    if _libcrypto is None:
        raise RuntimeError("OpenSSL libcrypto unavailable for AES-GCM decryption")

    ctx = _libcrypto.EVP_CIPHER_CTX_new()
    if not ctx:
        raise MemoryError("Failed to allocate EVP_CIPHER_CTX")
    try:
        cipher = _libcrypto.EVP_aes_256_gcm()
        if _libcrypto.EVP_DecryptInit_ex(ctx, cipher, None, None, None) != 1:
            raise RuntimeError("EVP_DecryptInit_ex failed")

        if _libcrypto.EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, len(nonce), None) != 1:
            raise RuntimeError("Failed to set IV length")

        if _libcrypto.EVP_DecryptInit_ex(ctx, None, None, key, nonce) != 1:
            raise RuntimeError("Failed to set key and nonce")

        out = ctypes.create_string_buffer(len(ciphertext) + 16)
        out_len = ctypes.c_int(0)

        res_upd = _libcrypto.EVP_DecryptUpdate(
            ctx, out, ctypes.byref(out_len), ciphertext, len(ciphertext)
        )
        if res_upd != 1:
            raise RuntimeError("EVP_DecryptUpdate failed")

        tag_buf = ctypes.create_string_buffer(tag, len(tag))
        if _libcrypto.EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_TAG, len(tag), tag_buf) != 1:
            raise RuntimeError("Failed to set expected GCM tag")

        dummy_len = ctypes.c_int(0)
        final_ptr = ctypes.cast(ctypes.byref(out, out_len.value), ctypes.c_char_p)
        res = _libcrypto.EVP_DecryptFinal_ex(ctx, final_ptr, ctypes.byref(dummy_len))
        if res <= 0:
            raise ValueError(
                "Decryption failed: authentication tag mismatch or corrupted ciphertext"
            )

        return out.raw[: out_len.value]
    finally:
        _libcrypto.EVP_CIPHER_CTX_free(ctx)
