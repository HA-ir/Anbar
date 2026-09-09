# BUG-28: Deploy v0.15.46 UI/UX Revamp to Falkenstein

## Status: COMPLETED

## Deployment Summary

- **Version**: v0.15.46 (commit 90c9271)
- **Server**: Falkenstein (dl.amiri-dev.ir)
- **Path**: /root/anbar
- **Port**: 8318
- **Container**: anbar-anbar-1 (healthy)

## Verification

```bash
curl http://127.0.0.1:8318/healthz
# Response: {"status":"ok","service":"anbar","version":"0.15.46"}
```

## Actions Taken

1. Pulled latest code from origin/main (commit 90c9271)
2. Built Docker image: anbar:prod
3. Deployed via docker compose up -d
4. Verified health check and version

## Time Completed

2026-09-07T21:35Z

---

## BUG-37: Missing files / wrong data directory on Falkenstein

### Status: FIXED

### Root Cause

The v0.15.50 deploy (BUG-36) removed the old container and started a new one.
The new container was created pointing at `/root/anbar/data` (1 object: `b.bin`)
instead of `/opt/anbar/data` (20 objects: all real files).

`/root/anbar/docker/compose.yaml` (local-dev compose) has a **relative**
volume: `../data:/app/data`.  Running `docker compose up -d` from
`/root/anbar/docker` resolves that to `/root/anbar/data` — NOT the
production data directory at `/opt/anbar/data`.

The production compose at `/opt/anbar/compose.yaml` correctly uses the
absolute paths `/opt/anbar/data:/app/data` and `/opt/anbar/secrets:/app/secrets`.

### Data Recovery

No data loss. The production SQLite DB at `/opt/anbar/data/anbar.db`
(376 KB, 20 objects, 331 audit logs) was intact the entire time.
The container just wasn't reading from it.

### Fix Applied

```bash
docker rm -f anbar-anbar-1
cd /opt/anbar
docker compose -f compose.yaml up -d
```

Container now mounts:
- `/opt/anbar/data` -> `/app/data`  (20 objects)
- `/opt/anbar/secrets` -> `/app/secrets`
- `/opt/anbar/.env` -> `/opt/anbar/.env`

### Verification

```
docker ps  ->  anbar-anbar-1  Up (healthy)  127.0.0.1:8318->8567/tcp
curl 127.0.0.1:8318/healthz  ->  {"status":"ok","service":"anbar","version":"0.15.50"}
docker exec anbar-anbar-1: /app/data/anbar.db -> 20 objects
```

### Prevention

Future deploys must always use: `cd /opt/anbar && docker compose -f compose.yaml up -d`
Never use `/root/anbar/docker/compose.yaml` for production deploys — its
relative volume paths resolve to the wrong data directory.

### Time Fixed

2026-09-09T18:05Z

---

## BUG-36: Deploy v0.15.50 to Falkenstein (gallery card size + Persian date fix)

### Status: DONE

### Deployment Summary

- **Version**: v0.15.50 (commit 3d7b0db, tag v0.15.50)
- **Server**: Falkenstein (dl.amiri-dev.ir)
- **Path**: /root/anbar
- **Port**: 8318
- **Container**: anbar-anbar-1 (healthy)

### What Changed

- Gallery cards slightly larger: minmax 150px→180px, thumbnail height 110px→130px
- Persian date in table view no longer shows "ساعت" — compact format: "۱۸ شهریور، ۱۲:۲۵"

### Verification

```bash
curl https://dl.amiri-dev.ir/healthz
# Response: {"status":"ok","service":"anbar","version":"0.15.50"}
```

### Actions Taken

1. Pulled latest code from origin/main (commit 3d7b0db)
2. Discovered __init__.py had stale __version__ = "0.15.49" — fixed to "0.15.50"
3. Built Docker image: anbar:prod
4. Removed old container and started fresh with anbar:prod image
5. Verified health check returns version 0.15.50

### Time Completed

2026-09-09T16:52Z

---

## BUG-39: Deploy v0.15.51 to Falkenstein (lightweight preview caching & 0ms folder navigation)

### Status: DONE

### Deployment Summary

- **Version**: v0.15.51 (commit 3f08bae, tag v0.15.51)
- **Server**: Falkenstein (dl.amiri-dev.ir)
- **Path**: /opt/anbar
- **Port**: 8318
- **Container**: anbar-anbar-1 (healthy)

### What Changed (v0.15.51)

- Video poster extraction via ffmpeg
- HTTP cache headers for previews
- Frontend folder view preservation (URL-based navigation state)
- Lightweight preview caching
- 0ms folder navigation (no redownloading when returning to Home)

### Files Changed

- `pyproject.toml` — version bump
- `src/anbar/__init__.py` — version bump
- `src/anbar/api/admin.py`
- `src/anbar/api/download.py` — HTTP cache headers
- `src/anbar/thumbs.py` — poster extraction + caching
- `src/anbar/ui/index.html` — folder view preservation
- `tests/test_e2e_playwright.py` — E2E tests
- `tests/test_thumbs.py` — thumbnail/caching tests
- `uv.lock` — lockfile update

### Verification

```bash
curl http://127.0.0.1:8318/healthz
# Response: {"status":"ok","service":"anbar","version":"0.15.51"}

docker ps
# anbar-anbar-1  Up (healthy)  127.0.0.1:8318->8567/tcp

# Data integrity
python3 -c "import sqlite3; con=sqlite3.connect('/opt/anbar/data/anbar.db'); print('objects:', con.execute('SELECT COUNT(*) FROM objects').fetchone()[0]); con.close()"
# objects: 20

# Memory usage
docker stats anbar-anbar-1 --no-stream
# 73.65MiB / 3.725GiB, 0.12% CPU
```

### Live Testing Results

- Health endpoint: ✅ returns version 0.15.51
- Container: ✅ healthy
- Database: ✅ 20 objects intact (no data loss)
- UI loads: ✅ https://dl.amiri-dev.ir/ serves the application
- Memory: ~74 MB RSS, 0.12% CPU — minimal footprint

### Time Completed

2026-09-09T21:55Z

---

## Previous Versions

### v0.15.50
Deployed: 2026-09-09
Commit: 3d7b0db
Note: Gallery card size increase, compact Persian date format

### v0.15.49
Deployed: 2026-09-07
Commit: fb84161
Note: __version__ mismatch bug — pyproject.toml said 0.15.50 but __init__.py had 0.15.49

### v0.15.46
Deployed: 2026-09-07 (previous release)
Commit: 90c9271

---
