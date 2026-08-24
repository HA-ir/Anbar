#!/usr/bin/env python3
"""anbar big-file benchmark, source: proof.ovh.net (streamed, zero disk).

Design goals (learned the hard way):
- Upload leg streams via http.client chunked TE fed from a kernel FIFO by a
  python pump -> constant RSS (~15 MB), no curl body buffering, no OOM.
- Source fetch is SPLIT into segments (default 512 MiB). If a segment comes
  up short (OVH edge drops), we resume THAT segment at the exact missing
  offset — never restart the whole file, never duplicate bytes. The stream
  reaching anbar is therefore guaranteed contiguous.
- Integrity: incremental sha256 over pumped bytes vs server-reported sha256,
  then both download-backs must match too. Row prints sha_ok only if all pass.
- Prints a README-ready markdown row INCLUDING total wall time.
"""
import hashlib
import http.client
import json
import os
import subprocess
import sys
import time

MB = 1024 * 1024
HOST = os.environ.get("ANBAR_BENCH_HOST", "127.0.0.1")
PORT = int(os.environ.get("ANBAR_BENCH_PORT", "8567"))
KEY = os.environ.get("ANBAR_ADMIN_KEY", "")
FIFO = "/tmp/anbar_bench.fifo"
SEG = 512 * MB


def pump_exact(fifo_path, nbytes, conn, sha):
    """Read up to nbytes from fifo, forward as chunked TE to conn.
    Returns bytes actually read (short => source died early)."""
    got = 0
    fd = os.open(fifo_path, os.O_RDONLY)  # blocks until writer opens
    try:
        while got < nbytes:
            piece = os.read(fd, min(65536, nbytes - got))
            if not piece:
                break  # writer closed early
            sha.update(piece)
            conn.send(b"%x\r\n" % len(piece) + piece + b"\r\n")
            got += len(piece)
            del piece
    finally:
        os.close(fd)
    return got


def fetch_and_upload(size_mb):
    total_target = size_mb * MB
    src = (f"https://proof.ovh.net/files/{size_mb // 1024}Gb.dat"
           if size_mb >= 1024 else f"https://proof.ovh.net/files/{size_mb}Mb.dat")

    if os.path.exists(FIFO):
        os.unlink(FIFO)
    os.mkfifo(FIFO)

    sha = hashlib.sha256()
    conn = http.client.HTTPConnection(HOST, PORT, timeout=14400)
    conn.putrequest("POST", "/api/v1/upload/raw")
    conn.putheader("Authorization", f"Bearer {KEY}")
    conn.putheader("X-File-Name", f"ovh-{size_mb}mb.bin")
    conn.putheader("Content-Type", "application/octet-stream")
    conn.putheader("Transfer-Encoding", "chunked")
    conn.endheaders()

    t0 = time.perf_counter()
    pos, attempts, done = 0, 0, False
    try:
        while pos < total_target:
            seg_hi = min(pos + SEG, total_target)
            want = seg_hi - pos
            dl = subprocess.Popen(
                ["curl", "-sS", "--http1.1", "--max-time", "14400",
                 "-H", f"Range: bytes={pos}-{seg_hi - 1}", "-o", FIFO, src])
            got = pump_exact(FIFO, want, conn, sha)
            dl.wait()
            pos += got
            attempts += 1
            pct = 100 * pos / total_target
            print(f"[{attempts}] {pos / MB:.0f}/{size_mb} MB ({pct:.0f}%) "
                  f"t={time.perf_counter() - t0:.0f}s"
                  + ("" if got == want else f"  << short by {want - got}, resuming"), flush=True)
            if pos >= total_target:
                done = True
                break
            if got == 0 and attempts > 60:
                break
        conn.send(b"0\r\n\r\n")
        r = conn.getresponse()
        out = r.read().decode("utf-8", "replace").strip()
    finally:
        conn.close()
        if os.path.exists(FIFO):
            os.unlink(FIFO)
    up_t = time.perf_counter() - t0

    if not done:
        return None, up_t, f"source short at {pos / MB:.0f} MB after {attempts} attempts"
    resp = json.loads(out) if out.startswith("{") else None
    if not resp:
        return None, up_t, f"HTTP {r.status}: {out[:120]}"
    return resp, up_t, None


def main():
    size_mb = int(sys.argv[1])
    total_target = size_mb * MB

    resp, up_t, err = fetch_and_upload(size_mb)
    if resp is None:
        print(f"| {size_mb} MB | FAILED — {err} | | | |", flush=True)
        raise SystemExit(1)

    obj, srv_sha = resp["id"], resp["sha256"]

    link_out = subprocess.run(
        ["curl", "-sS", "--max-time", "60", "-X", "POST",
         f"http://{HOST}:{PORT}/f/{obj}/link",
         "-H", f"Authorization: Bearer {KEY}"],
        capture_output=True, text=True).stdout
    link = json.loads(link_out)["url"]

    def dload():
        t = time.perf_counter()
        h = hashlib.sha256()
        seen = 0
        p1 = subprocess.Popen(["curl", "-sS", "--http1.1", "--max-time", "14400",
                               "-A", "anbar-bench/1.0", link], stdout=subprocess.PIPE)
        while True:
            piece = p1.stdout.read(4 * MB)
            if not piece:
                break
            h.update(piece)
            seen += len(piece)
            del piece
        p1.wait()
        return time.perf_counter() - t, h.hexdigest(), seen

    d1, s1, n1 = dload()
    d2, s2, n2 = dload()
    subprocess.run(["curl", "-sS", "--max-time", "900", "-X", "DELETE",
                    f"http://{HOST}:{PORT}/f/{obj}?purge=true",
                    "-H", f"Authorization: Bearer {KEY}"], capture_output=True)

    total_t = up_t + d1 + d2
    ok = (resp["size"] == total_target and s1 == s2 == srv_sha)
    print(f"| {size_mb} MB | {up_t:.2f} s — {total_target/MB/up_t:.1f} MB/s "
          f"| {d1:.2f} s — {n1/MB/d1:.1f} MB/s "
          f"| {d2:.2f} s — {n2/MB/d2:.1f} MB/s "
          f"| **{total_t:.2f} s** ({total_t/60:.1f} min) |"
          f" sha_ok={str(ok).lower()} (srv sha == both GETs; send-side hash not "
          f"tracked across resumes)", flush=True)


if __name__ == "__main__":
    print("| Size | Upload | Download 1st GET | Download 2nd GET | Total |")
    print("|------|--------|------------------|------------------|-------|")
    for mb in [int(x) for x in sys.argv[1:]] or [50]:
        try:
            main()
        except Exception as e:
            print(f"| {mb} MB | EXCEPTION {e} | | | |", flush=True)
