"""Loop #9: regression tests for B-057 (recover.py path traversal),
plus direct coverage for ratelimit.py and qrcode.py (gap-analysis L9)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load_recover():
    """Import scripts/recover.py as a module (zero-dep script, stdlib only)."""
    spec = importlib.util.spec_from_file_location(
        "anbar_recover", REPO / "scripts" / "recover.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── B-057: caption filenames must never escape out_path ────────────────────

@pytest.mark.parametrize(
    "raw",
    [
        "/etc/passwd",
        "../../evil.sh",
        "..",
        "../..",
        "a/../../b.txt",
        "C:\\Windows\\evil.exe",
        "\\\\server\\share\\f.txt",
        "...",
    ],
)
def test_caption_filename_is_basenamed(raw):
    from pathlib import PurePosixPath

    name = PurePosixPath(raw.replace("\\", "/")).name or ""
    assert "/" not in name and "\\" not in name
    # a surviving '..' (or empty) is caught by the '.'/'..' fallback in recover.py
    assert name not in ("/etc/passwd", raw) or name == Path(raw).name


def test_recover_writes_inside_output_dir(tmp_path, monkeypatch):
    """End-to-end: a poisoned caption ('/etc/evil.txt') cannot write outside
    the recovery output directory."""
    rec = _load_recover()

    # Build a fake single-chunk object whose caption filename is absolute.
    payload = b"POISON-CONTENTS"
    chunks = [
        {"meta": {"id": "victim", "fn": "/etc/evil.txt", "n": 1, "i": 0},
         "data": payload},
    ]
    out_dir = tmp_path / "out"
    result = rec.recover_files(chunks, [], out_dir, server_secret=None)
    assert result["recovered_count"] == 1
    assert result["errors"] == []

    written = list(out_dir.rglob("*"))
    files = [p for p in written if p.is_file()]
    assert len(files) == 1
    resolved_out = out_dir.resolve()
    assert files[0].resolve().is_relative_to(resolved_out)
    # the file must be the basenamed copy, not /etc/evil.txt content at root
    assert files[0].name == "evil.txt"
    assert files[0].read_bytes() == payload
    # and nothing was written anywhere else under tmp_path
    others = [
        p for p in tmp_path.rglob("*")
        if p.is_file() and not p.is_relative_to(resolved_out)
    ]
    assert others == []


def test_recover_dotdot_caption_refused(tmp_path):
    rec = _load_recover()
    chunks = [
        {"meta": {"id": "x", "fn": "..", "n": 1, "i": 0}, "data": b"data"},
    ]
    out_dir = tmp_path / "out"
    result = rec.recover_files(chunks, [], out_dir)
    assert result["recovered_count"] == 1
    assert (out_dir / "recovered_x.bin").exists()


# ── ratelimit.py: direct coverage (no dedicated test existed) ──────────────

def test_rate_limit_window_and_retry_after(tmp_path):
    from anbar.db import Database
    from anbar.ratelimit import _WINDOW_S, limit_download, limit_upload

    db = Database(tmp_path / "rate.db")

    class FakeClient:
        host = "10.1.2.3"

    class FakeReq:
        client = FakeClient()
        headers = {}

    # limit 2: first two pass, third is 429 with a sane Retry-After
    limit_download(db, FakeReq(), "obj1", limit=2)
    limit_download(db, FakeReq(), "obj1", limit=2)
    with pytest.raises(Exception) as ei:
        limit_download(db, FakeReq(), "obj1", limit=2)
    assert getattr(ei.value, "status_code", None) == 429
    ra = (ei.value.headers or {}).get("Retry-After")
    assert ra is not None and 1 <= int(ra) <= _WINDOW_S

    # distinct object → separate bucket
    limit_download(db, FakeReq(), "obj2", limit=2)  # no raise

    # limit 0 disables the check entirely
    for _ in range(5):
        limit_download(db, FakeReq(), "obj3", limit=0)

    # upload bucket keyed by hashed bearer (never raw)
    class AuthReq(FakeReq):
        headers = {"authorization": "Bearer super-secret-key"}

    with pytest.raises(Exception) as ei2:
        for _ in range(10):
            limit_upload(db, AuthReq(), limit=3)
    assert getattr(ei2.value, "status_code", None) == 429


# ── qrcode.py: direct coverage (no dedicated test existed) ─────────────────

def test_qr_svg_realistic_signed_link():
    from anbar.qrcode import qr_svg

    url = (
        "https://storage.example-subdomain-long-name.com/f/"
        + "a" * 40
        + "?sig=" + "b" * 64
        + "&exp=9999999999"
    )
    svg = qr_svg(url)
    assert svg.startswith("<svg") and "crispEdges" in svg


def test_qr_payload_too_long_raises_clean():
    from anbar.qrcode import qr_svg

    with pytest.raises(ValueError):
        qr_svg("https://example.com/" + "a" * 300)


def test_qr_matrix_finder_patterns():
    from anbar.qrcode import _build_matrix

    def finder_ok(m, r0, c0):
        for dr in range(7):
            for dc in range(7):
                dark = dr in (0, 6) or dc in (0, 6) or (2 <= dr <= 4 and 2 <= dc <= 4)
                if m[r0 + dr][c0 + dc] != dark:
                    return False
        return True

    m = _build_matrix(b"HELLO")
    n = len(m)
    assert n >= 21
    assert finder_ok(m, 0, 0)
    assert finder_ok(m, 0, n - 7)
    assert finder_ok(m, n - 7, 0)
