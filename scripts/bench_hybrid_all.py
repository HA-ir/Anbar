#!/usr/bin/env python3
"""Unified Hybrid Benchmark Runner (1 MB to 10 GB)

Runs end-to-end benchmark on running Anbar instance with Hybrid Bot CDN + MTProto:
Sizes: 1 MB, 8 MB, 45 MB, 100 MB, 500 MB, 1 GB, 5 GB, 10 GB
Streams payload directly through memory (zero-disk buffer)
Measures Upload Time & Throughput, Download Time & Throughput, Total Time
Verifies SHA-256 integrity
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time

import httpx

MB = 1024 * 1024
GB = 1024 * MB
BASE_URL = "http://127.0.0.1:8318"
ENV_PATH = "/opt/anbar/.env"


def get_admin_key() -> str:
    with open(ENV_PATH) as f:
        for line in f:
            if line.startswith("ANBAR_ADMIN_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise ValueError("ANBAR_ADMIN_KEY not found in .env")


def set_rate_limits(key: str, upload: int, download: int):
    url = f"{BASE_URL}/api/v1/admin/settings"
    try:
        with httpx.Client(timeout=10.0) as client:
            client.post(
                url,
                json={"rate_upload": upload, "rate_download": download},
                headers={"Authorization": f"Bearer {key}"},
            )
    except Exception as e:
        print(f"Warning: Failed setting rate limits: {e}")


def stream_generator(
    total_bytes: int,
    chunk_size: int = 1024 * 1024 * 2,
    sha_tracker: hashlib._Hash | None = None,
):
    pattern = b"ANBAR_HYBRID_BENCH_STREAM_BLOCK_DATA_2026_FAST_RELIABLE_" * 1170  # ~64KB
    pattern_len = len(pattern)
    sent = 0
    while sent < total_bytes:
        to_send = min(chunk_size, total_bytes - sent)
        reps = (to_send // pattern_len) + 1
        block = (pattern * reps)[:to_send]
        if sha_tracker is not None:
            sha_tracker.update(block)
        sent += len(block)
        yield block


def benchmark_size(size_bytes: int, key: str, client: httpx.Client) -> dict:
    size_mb = size_bytes / MB
    tag = f"{size_mb:.0f} MB" if size_mb < 1024 else f"{size_mb/1024:.0f} GB"
    print(
        f"\n{'='*70}\n>>> Benchmarking {tag} ({size_bytes:,} bytes)\n{'='*70}",
        flush=True,
    )

    # ── 1. Upload Phase ──
    print(f"[{tag}] Uploading...", flush=True)
    sha_up = hashlib.sha256()
    upload_url = f"{BASE_URL}/api/v1/upload/raw?filename=bench_{int(size_mb)}mb.bin"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/octet-stream",
        "Content-Length": str(size_bytes),
    }

    t0_up = time.monotonic()
    resp = client.post(
        upload_url,
        content=stream_generator(size_bytes, chunk_size=2 * MB, sha_tracker=sha_up),
        headers=headers,
        timeout=httpx.Timeout(7200.0, connect=30.0, read=7200.0, write=7200.0),
    )
    t_up = time.monotonic() - t0_up

    if resp.status_code != 200:
        print(f"[{tag}] Upload FAILED: HTTP {resp.status_code} - {resp.text}")
        return {"size_label": tag, "error": f"Upload HTTP {resp.status_code}"}

    up_json = resp.json()
    obj_id = up_json["id"]
    up_speed = size_mb / t_up
    expected_sha = sha_up.hexdigest()
    print(f"[{tag}] Upload OK in {t_up:.2f}s ({up_speed:.2f} MB/s) | ID: {obj_id}", flush=True)

    # ── 2. Download Phase ──
    print(f"[{tag}] Downloading via Hybrid Stream...", flush=True)
    dl_url = f"{BASE_URL}/f/{obj_id}"
    dl_headers = {"Authorization": f"Bearer {key}"}

    sha_dl = hashlib.sha256()
    dl_bytes = 0
    t0_dl = time.monotonic()
    last_log = t0_dl

    with client.stream(
        "GET",
        dl_url,
        headers=dl_headers,
        timeout=httpx.Timeout(7200.0, connect=30.0, read=7200.0, write=7200.0),
    ) as resp_dl:
        if resp_dl.status_code != 200:
            print(f"[{tag}] Download FAILED: HTTP {resp_dl.status_code}")
            return {"size_label": tag, "error": f"Download HTTP {resp_dl.status_code}"}

        for chunk in resp_dl.iter_bytes(chunk_size=4 * MB):
            sha_dl.update(chunk)
            dl_bytes += len(chunk)
            now = time.monotonic()
            if size_bytes >= 500 * MB and (now - last_log >= 15):
                cur_s = (dl_bytes / MB) / (now - t0_dl)
                pct = (dl_bytes / size_bytes) * 100
                mb_so_far = dl_bytes / MB
                el = now - t0_dl
                print(
                    f"[{tag}] Progress: {pct:5.1f}% ({mb_so_far:.1f} MB in {el:.1f}s — {cur_s:.1f} MB/s)",
                    flush=True,
                )
                last_log = now

    t_dl = time.monotonic() - t0_dl
    dl_speed = size_mb / t_dl
    actual_sha = sha_dl.hexdigest()
    sha_ok = actual_sha == expected_sha
    total_time = t_up + t_dl

    sha_stat = "OK" if sha_ok else "FAIL"
    print(
        f"[{tag}] Download OK in {t_dl:.2f}s ({dl_speed:.2f} MB/s) | SHA-256: {sha_stat}",
        flush=True,
    )

    # Purge
    try:
        purge_url = f"{BASE_URL}/f/{obj_id}?purge=true"
        client.delete(purge_url, headers={"Authorization": f"Bearer {key}"})
    except Exception:
        pass

    return {
        "size_label": tag,
        "size_bytes": size_bytes,
        "upload_time": round(t_up, 2),
        "upload_speed": round(up_speed, 2),
        "download_time": round(t_dl, 2),
        "download_speed": round(dl_speed, 2),
        "total_time": round(total_time, 2),
        "sha_ok": sha_ok,
    }


def main():
    parser = argparse.ArgumentParser(description="Anbar Hybrid Speed Benchmark")
    default_sizes = ["1MB", "8MB", "45MB", "100MB", "500MB", "1GB", "5GB", "10GB"]
    parser.add_argument("--sizes", nargs="+", type=str, default=default_sizes)
    parser.add_argument("--out", type=str, default="/tmp/bench_hybrid_results.json")
    args = parser.parse_args()

    size_map = {
        "1MB": 1 * MB,
        "8MB": 8 * MB,
        "45MB": 45 * MB,
        "100MB": 100 * MB,
        "500MB": 500 * MB,
        "1GB": 1 * GB,
        "5GB": 5 * GB,
        "10GB": 10 * GB,
    }

    selected_sizes = [size_map[s.upper()] for s in args.sizes if s.upper() in size_map]
    if not selected_sizes:
        print("No valid sizes selected")
        sys.exit(1)

    key = get_admin_key()
    print("Temporarily setting rate limits to unlimited for benchmark...", flush=True)
    set_rate_limits(key, 0, 0)

    client = httpx.Client(timeout=httpx.Timeout(7200.0, connect=30.0, read=7200.0, write=7200.0))
    results = []

    try:
        for sz in selected_sizes:
            res = benchmark_size(sz, key, client)
            results.append(res)
            with open(args.out, "w") as f:
                json.dump(results, f, indent=2)
            time.sleep(1.0)
    finally:
        print("\nRestoring standard rate limits...", flush=True)
        set_rate_limits(key, 5, 10)
        client.close()

    print("\n" + "=" * 80)
    print("HYBRID BENCHMARK RESULTS (v0.15.7)")
    print("=" * 80)
    print("| Size | Upload | Download | Total | SHA-256 |")
    print("| :--- | :--- | :--- | :--- | :--- |")
    for r in results:
        if "error" in r:
            print(f"| {r['size_label']} | ERROR: {r['error']} | - | - | - |")
        else:
            up_s = f"{r['upload_time']} s — {r['upload_speed']} MB/s"
            dl_s = f"{r['download_time']} s — {r['download_speed']} MB/s"
            tot_s = f"{r['total_time']} s"
            sha_s = "OK" if r["sha_ok"] else "FAIL"
            print(f"| {r['size_label']} | {up_s} | {dl_s} | {tot_s} | {sha_s} |")


if __name__ == "__main__":
    main()
