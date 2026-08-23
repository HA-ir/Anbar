#!/usr/bin/env python3
"""anbar benchmark harness — repeatable speed test against a running server.

Measures upload / first-GET / second-GET (cache) latency and throughput for
a size ladder, using the signed-link download path. Prints a markdown table
ready to paste into README's "Speed test" section.

Usage:
  export ANBAR_BASE_URL=http://127.0.0.1:8567 ANBAR_ADMIN_KEY=***
  .venv/bin/python scripts/bench.py --sizes 1 8 45 [--repeat 2] [--keep]

Notes:
  - Sizes are MB. Files are random bytes generated once per size.
  - "2nd GET" is meaningful with the LRU cache enabled; without cache the
    two GETs measure Telegram CDN variance instead.
  - Nothing is retained: every object is purged unless --keep is passed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

MB = 1024 * 1024


def http(method: str, url: str, *, key: str | None = None, data: bytes | None = None,
         headers: dict[str, str] | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", "anbar-bench/1.0")  # CDNs block default python UA
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=3600) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def http_stream_to_file(method: str, url: str, out_path: str, *, key: str | None = None,
                        headers: dict[str, str] | None = None) -> tuple[int, str]:
    """GET streaming to disk; returns (status, sha256 hex). RSS stays ~1 MB."""
    sha = hashlib.sha256()
    req = urllib.request.Request(url, method=method)
    req.add_header("User-Agent", "anbar-bench/1.0")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=3600) as r, open(out_path, "wb") as f:
            while True:
                piece = r.read(1 * MB)
                if not piece:
                    break
                sha.update(piece)
                f.write(piece)
                del piece
        return 200, sha.hexdigest()
    except urllib.error.HTTPError as e:
        e.read()
        return e.code, ""


def bench_size(base: str, key: str, size_mb: int, keep: bool = False) -> dict:
    # stream-friendly: build the payload in 1 MB pieces to keep RSS low,
    # then hash + upload from a temp file instead of holding it all in RAM.
    import tempfile
    sha = hashlib.sha256()
    tmp = tempfile.NamedTemporaryFile(delete=False, dir="/root/anbar_bench_big")
    piece = bytes(1 * MB)
    written = 0
    target = size_mb * MB
    while written < target:
        n = min(len(piece), target - written)
        chunk = os.urandom(n)
        sha.update(chunk)
        tmp.write(chunk)
        written += n
    tmp.close()
    payload_path = tmp.name
    payload_sha = sha.hexdigest()
    size_bytes = written

    def _cleanup():
        try:
            os.unlink(payload_path)
        except OSError:
            pass

    if not keep:
        try:
            import atexit
            atexit.register(_cleanup)
        except Exception:
            pass

    t0 = time.perf_counter()
    with open(payload_path, "rb") as f:
        st, body = http("POST", f"{base}/api/v1/upload/raw", key=key, data=f,
                        headers={"X-File-Name": f"bench-{size_mb}mb.bin",
                                 "Content-Length": str(size_bytes)})
    up_t = time.perf_counter() - t0
    if st != 200:
        sys.exit(f"upload failed ({st}): {body[:200]}")
    obj = json.loads(body)["id"]

    st, link_body = http("POST", f"{base}/f/{obj}/link", key=key)
    if st != 200:
        sys.exit(f"link mint failed ({st})")
    url = json.loads(link_body)["url"]

    t0 = time.perf_counter()
    dl_path = payload_path + ".dl1"
    st, dl_sha = http_stream_to_file("GET", url, dl_path)
    d1_t = time.perf_counter() - t0
    os.unlink(dl_path)
    if st != 200 or dl_sha != payload_sha:
        sys.exit(f"first GET failed/corrupt ({st})")

    t0 = time.perf_counter()
    dl2_path = payload_path + ".dl2"
    st, dl2_sha = http_stream_to_file("GET", url, dl2_path)
    d2_t = time.perf_counter() - t0
    os.unlink(dl2_path)
    if st != 200 or dl2_sha != payload_sha:
        sys.exit(f"second GET failed/corrupt ({st})")

    if not keep:
        http("DELETE", f"{base}/f/{obj}?purge=true", key=key)

    return {
        "size_mb": size_mb,
        "up_s": up_t, "up_mbs": size_bytes / MB / up_t,
        "d1_s": d1_t, "d1_mbs": size_bytes / MB / d1_t,
        "d2_s": d2_t, "d2_mbs": size_bytes / MB / d2_t,
    }


def fmt(r: dict) -> str:
    return (f"| {r['size_mb']} MB | {r['up_s']:.2f} s — {r['up_mbs']:.1f} MB/s "
            f"| {r['d1_s']:.2f} s — {r['d1_mbs']:.1f} MB/s "
            f"| {r['d2_s']:.2f} s — {r['d2_mbs']:.1f} MB/s |")


def main() -> None:
    ap = argparse.ArgumentParser(description="anbar benchmark harness")
    ap.add_argument("--base-url", default=os.environ.get("ANBAR_BASE_URL", "http://127.0.0.1:8567"))
    ap.add_argument("--key", default=os.environ.get("ANBAR_ADMIN_KEY"),
                    help="admin key (or set ANBAR_ADMIN_KEY)")
    ap.add_argument("--sizes", type=int, nargs="+", default=[1, 8, 45], help="sizes in MB")
    ap.add_argument("--keep", action="store_true", help="do not purge bench objects")
    args = ap.parse_args()
    if not args.key:
        sys.exit("need --key or ANBAR_ADMIN_KEY")

    print("| Size | Upload | Download 1st GET | Download 2nd GET |")
    print("|------|--------|------------------|------------------|")
    for mb in args.sizes:
        print(fmt(bench_size(args.base_url.rstrip("/"), args.key, mb, args.keep)), flush=True)


if __name__ == "__main__":
    main()
