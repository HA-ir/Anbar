# BUG-38 to BUG-42: Stabilization & UX Reliability (v0.15.57)

## Status: FIXED & VERIFIED E2E

### Overview
Addresses 5 core architectural and UX defects identified in Anbar stabilization specification (`specs/001-ux-reliability-stabilization`):

1. **BUG-38 (File selection freezes main thread)**:
   - *Root Cause*: `#selAllBtn.onclick` and `setSelectMode(false)` invoked `renderRows()` / `renderGallery()`, synchronously tearing down and recreating all DOM nodes (up to 500 cards/rows with media elements and listeners). Also `updateSelBar()` triggered a full array filter scan on every single click.
   - *Fix*: Decoupled selection state from rendering. Selection toggles mutate `.selected` classes and checkbox `.checked` properties in-place without rebuilding DOM elements.
   - *Verification*: Playwright E2E benchmark (`test_large_file_selection_performance`) asserts select all on 100+ files executes in <100ms with DOM nodes preserved intact.

2. **BUG-39 (Search string resurrection on clear)**:
   - *Root Cause*: Clearing `#fSearch` failed to cancel `searchDebounceTimer` (75ms). Overlapping timers or stale DOM trees in `folderViewCache` reinstated superseded search queries after a delay.
   - *Fix*: `#fClear.onclick` and backspace clearing synchronously call `clearTimeout(searchDebounceTimer)`, reset `searchDebounceTimer = null`, evict search cache keys, and keep `fQuery` and input state atomically synchronized.
   - *Verification*: Playwright E2E test `test_search_clear_race_safety` asserts query never resurfaces after typing and rapid clearing.

3. **BUG-40 (Cold restart blank screen until Settings opened)**:
   - *Root Cause*: `showApp()` fired `Promise.all([api("/admin/status"), api("/admin/objects")])` concurrently on startup. When the session cookie was missing/expired, both requests failed with 401. `api()` attempted re-login but threw 401 without retrying the original call, setting `files = []` and leaving the file list blank. Opening Settings issued sequential calls that repaired the cookie.
   - *Fix*: Updated `api()` to await a coalesced singleton `_reLoginPromise` on 401 and transparently replay the failed request once before returning or throwing.
   - *Verification*: Playwright E2E test `test_cold_start_direct_file_loading` verifies files load immediately on initial render without opening Settings.

4. **BUG-41 (File move modal premature closing and circular folder move)**:
   - *Root Cause*: `doMove()` closed `#moveModal` before network requests began, provided no progress feedback, and silently treated invalid moves (into self/subfolder) as false successes (`ok++`).
   - *Fix*: Kept `#moveModal` visible with loading spinner and disabled buttons during flight; added client-side validation preventing circular folder moves and same-destination moves; added granular completion reporting.
   - *Verification*: Playwright E2E test `test_file_move_validation_and_progress` verifies circular move rejection, progress feedback, and successful move reconciliation.

5. **BUG-42 (False-negative MKV browser playback error)**:
   - *Root Cause*: `openFileModal()` assumed `.mkv` extension meant unplayable and unconditionally rendered a failure banner on any video error, ignoring Chromium's native Matroska demuxing capability.
   - *Fix*: Configured `<video>` with format-specific `<source type="video/x-matroska">` hints, enabled native Matroska playback in Chromium, and inspected `video.error.code` (`MEDIA_ERR_DECODE` vs `MEDIA_ERR_NETWORK`) before falling back.
   - *Verification*: Playwright E2E test `test_mkv_video_playback_detection` verifies native MKV video playback in Chromium without false-negative error banners.

---

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

### v0.15.58 — Product Quality & UX Overhaul
Date: 2026-10-01
Scope: Specs/002-ux-product-overhaul (Move workflow redesign, design system, async reliability, empty states)

#### Defects & UX Flaws Resolved
1. **Manual Path Typing in Move Workflow**:
   - *Issue*: Relocating an item into a nested folder required typing the complete path string manually.
   - *Fix*: Implemented an interactive hierarchical folder browser with direct child folder drill-down, navigable breadcrumb trail (`#moveBreadcrumbs`), prominent destination path display (`#moveTargetBadge`), real-time folder search filter, and automated circular move visual disabling (`.disabled`).
2. **Design Inconsistency & Toolbar Clutter**:
   - *Issue*: 11 disconnected toolbar buttons on desktop; awkward wrapping and fragmented rows on mobile.
   - *Fix*: Grouped into 3 semantic flex clusters (`.toolbar-group-primary`, `.toolbar-group-view`, `.toolbar-group-actions`), standardized button dimensions (`--btn-h: 36px`, `--btn-h-sm: 30px`, `--btn-radius: 10px`), and added responsive mobile label collapsing (<480px).
3. **Async Race Conditions on Mutating Modals**:
   - *Issue*: Rapid double-clicking on folder creation, file rename, or link minting could dispatch duplicate network requests.
   - *Fix*: Implemented universal `guardModalSubmit()` across all modals with active in-flight spinners, disabled secondary clicks, and guaranteed error reset.
4. **Media Resource Leaks**:
   - *Issue*: Closing preview modal while playing video or audio kept decoders and streams active in memory.
   - *Fix*: Added explicit `pause()`, `removeAttribute("src")`, and `load()` cleanup on modal dismiss.
5. **Contextual Empty States**:
   - *Issue*: Empty folders and zero search results presented raw text.
   - *Fix*: Designed rich contextual SVG illustrations, descriptive copy, and operational shortcut buttons ("Upload Files", "Clear Search").
6. **Video Seeking Stalled / Infinite Loading State (BUG-51)**:
   - *Issue*: Playing a video worked initially, but seeking forward to a later point caused the video to freeze indefinitely in a waiting/loading state and never resume.
   - *Root Cause 1 (Rate Limiting)*: `limit_download` in `src/anbar/api/download.py` was applied unconditionally across all HTTP requests to `/f/{id}` (default 10 req/min). Video initial load takes 2-4 Range requests for container headers; seeking forward issues 2-3 more Range requests. Within seconds, normal scrubbing crossed 10 requests, returning HTTP 429 Too Many Requests. HTML5 `<video>` cannot recover from 429 on Range probes, entering an unrecoverable stall.
   - *Root Cause 2 (BaseHTTPMiddleware Disconnect Crash)*: `_SecurityHeadersMiddleware` was implemented via Starlette's `BaseHTTPMiddleware`. When a browser seeks, it aborts earlier in-flight range streams. `BaseHTTPMiddleware` caught the cancellation and synthesized `send({"type": "http.response.body", "body": b"", "more_body": False})`. Because `Content-Length` was declared on the 206 response, Uvicorn raised `RuntimeError: Response content shorter than Content-Length`, terminating ASGI connection handling and breaking subsequent pipelined requests.
   - *Root Cause 3 (Prefetch Congestion)*: Lookahead prefetching eagerly spawned 2 full chunk background downloads (up to 32MB-98MB) before the active seek chunk yielded its first byte, saturating backend bandwidth.
   - *Fix*:
     1. Exempted HTTP Range requests from the per-minute full-download rate limiter in `src/anbar/api/download.py` (`if not request.headers.get("range"): limit_download(...)`), matching the existing architectural rule that Range probes are not full downloads.
     2. Re-implemented `_SecurityHeadersMiddleware` in `src/anbar/main.py` as a pure ASGI middleware intercepting `http.response.start`, completely eliminating `BaseHTTPMiddleware` and its disconnect crashes.
     3. Refactored multi-segment streaming into single-chunk lookahead pipelining, ensuring the active seek chunk receives 100% bandwidth immediately.
   - *Verification*: Automated Playwright E2E test `test_video_playback_and_seeking` exercising multiple forward and backward seeks on 10-minute MP4 and MKV videos with zero 429s or playback stalls.

#### Automated E2E Verification
- Playwright tests: 25 passing end-to-end browser tests (`tests/test_e2e_playwright.py`).
- 5-level directory drill-down and breadcrumb ascension verified in headless Chromium.
- Mobile viewport touch targets verified (≥36px) with zero horizontal overflow.

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
