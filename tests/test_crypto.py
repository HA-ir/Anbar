"""v0.11: AES-256-GCM chunk encryption tests."""

from __future__ import annotations

from anbar.crypto import decrypt_gcm, derive_key_256, encrypt_gcm

ADMIN = {"Authorization": "Bearer test-admin-key"}


def test_crypto_aes_gcm_direct():
    key = derive_key_256("my-secret-password-123")
    original = b"Super confidential payload that should never be plaintext on telegram servers"

    # Encrypt
    encrypted = encrypt_gcm(original, key)
    assert encrypted != original
    assert len(encrypted) == len(original) + 12 + 16  # Nonce (12B) + Tag (16B) + Ciphertext

    # Decrypt
    decrypted = decrypt_gcm(encrypted, key)
    assert decrypted == original


def test_crypto_tamper_fails():
    key = derive_key_256("my-secret-password-123")
    original = b"Hello Anbar Zero Knowledge"
    encrypted = bytearray(encrypt_gcm(original, key))

    # Tamper one byte in ciphertext
    encrypted[-1] ^= 0xFF

    try:
        decrypt_gcm(bytes(encrypted), key)
        raise AssertionError("Decryption should have failed on tampered ciphertext")
    except ValueError:
        pass  # Expected tag authentication failure
