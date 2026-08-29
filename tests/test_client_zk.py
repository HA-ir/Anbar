from __future__ import annotations

import subprocess

import pytest

from anbar.crypto import client_zk_decrypt, client_zk_encrypt


def test_client_zk_roundtrip():
    secret_text = b"Highly confidential patient record - Zero Knowledge!"
    password = "MyComplexPassword#2026"

    enc = client_zk_encrypt(secret_text, password)
    assert enc.startswith(b"ANBAR_ZK1")
    assert len(enc) > len(secret_text)

    dec = client_zk_decrypt(enc, password)
    assert dec == secret_text


def test_client_zk_wrong_password():
    secret_text = b"Secret data"
    password = "CorrectPassword"

    enc = client_zk_encrypt(secret_text, password)
    with pytest.raises(ValueError, match="Decryption failed|Invalid"):
        client_zk_decrypt(enc, "WrongPassword")


def test_client_zk_corrupted_payload():
    secret_text = b"Some data"
    password = "Pass"

    enc = client_zk_encrypt(secret_text, password)
    corrupted = bytearray(enc)
    corrupted[-1] ^= 0xFF  # tamper last byte

    with pytest.raises(ValueError):
        client_zk_decrypt(bytes(corrupted), password)


def test_client_zk_cli_roundtrip(tmp_path):
    plain_file = tmp_path / "plain.txt"
    enc_file = tmp_path / "plain.txt.enc"
    dec_file = tmp_path / "restored.txt"

    original = b"Command line client ZK test!"
    plain_file.write_bytes(original)

    import sys

    # Encrypt
    res_enc = subprocess.run(
        [
            sys.executable,
            "-m",
            "anbar.cli",
            "encrypt",
            str(plain_file),
            "-p",
            "CliPass123",
            "-o",
            str(enc_file),
        ],
        capture_output=True,
        text=True,
    )
    assert res_enc.returncode == 0
    assert enc_file.exists()

    # Decrypt
    res_dec = subprocess.run(
        [
            sys.executable,
            "-m",
            "anbar.cli",
            "decrypt",
            str(enc_file),
            "-p",
            "CliPass123",
            "-o",
            str(dec_file),
        ],
        capture_output=True,
        text=True,
    )
    assert res_dec.returncode == 0
    assert dec_file.read_bytes() == original
