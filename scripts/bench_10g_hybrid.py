#!/usr/bin/env python3
"""10GB Hybrid Benchmark (Robust Client):
Upload 10GB from /root/ovh10g/ via MTProto + bot harvester.
Download 10GB via Hybrid Bot CDN (with MTProto fallback).
Verify exact SHA256 without saving 10GB to disk (disk-friendly).
"""
import glob
import hashlib
import json
import os
import sys
import time
import httpx

PARTS_DIR = "/root/ovh10g"
EXPECTED_SHA = "b626371c7c9c245bfc9ac8f6ea1c6bef735bfadb73ce95427f74e040b1c2254b"
BASE_URL = "http://127.0.0.1:8318"
ENV_PATH = "/opt/anbar/.env"

def get_keys():
    api_key = None
    admin_key = None
    with open(ENV_PATH) as f:
        for line in f:
            if line.startswith("ANBAR_API_KEY="):
                api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
            if line.startswith("ANBAR_ADMIN_KEY="):
                admin_key = line.split("=", 1)[1].strip().strip('"').strip("'")
    return api_key, admin_key

def part_generator(parts, chunk_size=1024*1024*2):
    for p in parts:
        with open(p, "rb") as f:
            while chunk := f.read(chunk_size):
                yield chunk

def main():
    api_key, admin_key = get_keys()
    parts = sorted(glob.glob(f"{PARTS_DIR}/part_*.bin"))
    if not parts:
        print(f"Error: no parts in {PARTS_DIR}")
        sys.exit(1)

    total_bytes = sum(os.path.getsize(p) for p in parts)
    print(f"=== 10GB Hybrid Benchmark ===")
    print(f"Total parts: {len(parts)} | Total size: {total_bytes / (1024**3):.2f} GiB ({total_bytes} bytes)")
    print(f"Target URL: {BASE_URL}")

    client = httpx.Client(timeout=httpx.Timeout(7200.0, connect=30.0, read=7200.0, write=7200.0))

    # ── 1. Upload Phase ──────────────────────────────────────────────
    print("\n[Phase 1/2] Starting 10GB MTProto Upload + Bot Harvesting...", flush=True)
    upload_url = f"{BASE_URL}/api/v1/upload/raw?filename=10Gb-hybrid-bench.bin"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/octet-stream",
        "Content-Length": str(total_bytes),
    }

    t0 = time.monotonic()
    r = client.post(upload_url, content=part_generator(parts), headers=headers)
    t_up = time.monotonic() - t0

    if r.status_code != 200:
        print(f"Upload FAILED with HTTP {r.status_code}: {r.text}")
        sys.exit(1)

    up_res = r.json()
    obj_id = up_res["id"]
    up_mbps = (total_bytes / (1024 * 1024)) / t_up
    print(f"Upload Complete! Object ID: {obj_id}")
    print(f"Upload Wall Time: {t_up:.1f} s ({t_up/60:.1f} min)")
    print(f"Upload Throughput: {up_mbps:.2f} MB/s")
    print(f"Server reported SHA: {up_res.get('sha256')}")

    # Verify manifest and harvested bot_file_id count
    import sqlite3
    db = sqlite3.connect("file:/opt/anbar/data/anbar.db?mode=ro", uri=True)
    m_raw = db.execute("SELECT manifest FROM objects WHERE id=?", (obj_id,)).fetchone()[0]
    manifest = json.loads(m_raw)
    chunks = manifest.get("chunks", [])
    bot_fids = sum(1 for c in chunks if c.get("b"))
    print(f"Manifest chunk count: {len(chunks)} | Chunks with harvested Bot file_id: {bot_fids}/{len(chunks)}")

    # ── 2. Download Phase ────────────────────────────────────────────
    print("\n[Phase 2/2] Starting 10GB Hybrid Download (Bot CDN + fallback)...", flush=True)
    dl_url = f"{BASE_URL}/f/{obj_id}"
    dl_headers = {"Authorization": f"Bearer {api_key}"}

    h = hashlib.sha256()
    dl_bytes = 0
    t0_dl = time.monotonic()
    last_print = t0_dl

    with client.stream("GET", dl_url, headers=dl_headers) as resp:
        if resp.status_code != 200:
            print(f"Download HTTP Error {resp.status_code}")
            sys.exit(1)
        for chunk in resp.iter_bytes(chunk_size=1024*1024*4):
            h.update(chunk)
            dl_bytes += len(chunk)
            now = time.monotonic()
            if now - last_print >= 30:
                el = now - t0_dl
                cur_mbps = (dl_bytes / (1024 * 1024)) / el
                pct = (dl_bytes / total_bytes) * 100
                print(f"[Progress] {pct:5.1f}% | {dl_bytes/(1024**3):.2f}/{total_bytes/(1024**3):.2f} GiB in {el:.0f}s ({cur_mbps:.1f} MB/s)", flush=True)
                last_print = now

    t_dl = time.monotonic() - t0_dl
    dl_mbps = (total_bytes / (1024 * 1024)) / t_dl
    calc_sha = h.hexdigest()

    print(f"\nDownload Complete!")
    print(f"Download Wall Time: {t_dl:.1f} s ({t_dl/60:.1f} min)")
    print(f"Download Throughput: {dl_mbps:.2f} MB/s")
    print(f"Calculated SHA256: {calc_sha}")
    print(f"Expected   SHA256: {EXPECTED_SHA}")
    print(f"INTEGRITY VERIFIED: {calc_sha == EXPECTED_SHA}")

    # Output JSON summary
    summary = {
        "object_id": obj_id,
        "size_bytes": total_bytes,
        "upload_time_s": round(t_up, 1),
        "upload_mbps": round(up_mbps, 2),
        "download_time_s": round(t_dl, 1),
        "download_mbps": round(dl_mbps, 2),
        "harvested_chunks": f"{bot_fids}/{len(chunks)}",
        "sha_match": calc_sha == EXPECTED_SHA,
    }
    with open("/tmp/bench_10g_hybrid_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSummary saved to /tmp/bench_10g_hybrid_summary.json")

if __name__ == "__main__":
    main()
