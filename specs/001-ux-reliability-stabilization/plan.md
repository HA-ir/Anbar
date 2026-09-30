# Implementation Plan: Anbar Stabilization and UX Reliability

**Branch**: `001-ux-reliability-stabilization` | **Date**: 2026-09-30 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-ux-reliability-stabilization/spec.md`

## Summary

This plan provides an evidence-based technical implementation blueprint to resolve five interconnected architectural and UX stability defects in Anbar:
1. **Selection Freezes**: In-place DOM state manipulation and event delegation replacing synchronous DOM teardowns (`renderRows()`/`renderGallery()`).
2. **Move UX & Safety**: Explicit move state machine with active progress indicators, client-side circular path validation, and granular completion reporting.
3. **MKV Media Playback**: Capability-aware media streaming with explicit MIME type hints, browser Matroska demuxing support, and `video.error` diagnostic inspection.
4. **Search Synchronization**: Synchronous debounce timer invalidation, cache key clearing, and atomic input/memory binding to prevent search string resurrection.
5. **Cold-Start File Loading**: Deterministic authentication serialization and transparent single-retry on 401 in `api()`, eliminating any operational dependency on Settings.
6. **Deployment Continuity**: Reproducible local-to-remote deployment workflow targeting `/opt/anbar` on Falkenstein with strict volume and credential protection.

---

## Technical Context

**Language/Version**: Python 3.10+ (Backend), Vanilla JavaScript (ES2022+ / HTML5 in `src/anbar/ui/index.html`)  
**Primary Dependencies**: FastAPI, Uvicorn, SQLite3 (WAL mode), Telethon (MTProto), Pillow (thumbnails)  
**Storage**: SQLite database (`/opt/anbar/data/anbar.db`), Telegram cloud (chunks via Bot API & MTProto)  
**Testing**: `pytest`, `pytest-asyncio`, `playwright` (headless Chromium E2E)  
**Target Platform**: Linux (Development laptop & Falkenstein VPS production)  
**Project Type**: Web application & Telegram-backed object storage gateway  
**Performance Goals**: UI selection frame times <50ms for 500 files; startup file load <1.5s; video playback start <1.0s  
**Constraints**: Zero local file retention, vanilla JS in single-file UI (`index.html`), zero secret leakage in Git, absolute mount paths (`/opt/anbar`)

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Principle I (Correctness over superficial patching)**: PASS. Fixes address root causes (in-place DOM manipulation, retry logic in `api()`, proper media demuxing) rather than CSS/string hacks.
- **Principle II (Root-cause fixes over symptom suppression)**: PASS. Solves the 401 re-login race condition and timer leaks where all flows converge.
- **Principle III & IV (User-facing tests & E2E verification)**: PASS. All user-facing changes accompanied by unit tests and automated Playwright E2E tests in real Chromium browsers.
- **Principle V (Reliable browser capability detection)**: PASS. Removes crude `.mkv` extension assumptions in favor of MIME hints and `video.error` status codes.
- **Principle VI (Race-safe asynchronous state)**: PASS. Solves concurrency races in search debouncing, move execution, and startup authentication.
- **Principle VII (Restart and recovery verification)**: PASS. Explicit restart/recovery validation to guarantee files load directly after cold boot.
- **Principle VIII (Deterministic authentication)**: PASS. Serializes auth checks and implements singleton re-login promises.
- **Principle IX & X (Persistent records & atomic documentation)**: PASS. `docs/WORKING_RECORD.md` and documentation files updated alongside code.
- **Principle XI, XII & XIII (Deployment reproducibility, secrets protection & local tooling)**: PASS. Strict `/opt/anbar` mounts, untracked deployment helpers, and zero credential leakage.

---

## Project Structure

### Documentation (this feature)

```text
specs/001-ux-reliability-stabilization/
├── plan.md              # This implementation plan
├── research.md          # Technical choices and architecture decisions
├── data-model.md        # Entities, states, and lifecycle transitions
├── quickstart.md        # Runnable validation and test guide
├── contracts/           # API and client state machine contracts
│   └── api-contracts.md
└── checklists/          # Requirements and quality checklists
    └── requirements.md
```

### Source Code Paths

```text
src/anbar/
├── ui/
│   └── index.html       # Primary UI: selection, move modal, search sync, video player, boot/api
├── api/
│   ├── admin.py         # Admin objects listing, move, folder rename endpoints
│   ├── download.py      # Media streaming and Range request headers
│   └── web.py           # Webauth login, logout, and session minting
├── auth.py              # Authentication guards and role checks
├── main.py              # Application factory, lifespan, and backend initialization
└── storage/             # Telegram storage backends (bot, mtproto, harvester)

tests/
├── test_e2e_playwright.py       # Playwright E2E browser test journeys
├── test_mkv_video_preview.py    # Media and MKV streaming tests
├── test_folders.py              # Folder move and rename integration tests
└── test_runtime_settings.py     # Administrative settings and auth tests
```

---

## Detailed Implementation Phases

### Phase 1 — Architecture and State Audit
1. **Frontend State Mapping (`index.html`)**:
   - Trace all global state variables: `files`, `curFolderPrefix`, `fQuery`, `fType`, `fSortMode`, `selSet`, `selectMode`, `viewMode`, `folderViewCache`.
   - Map async triggers: `refresh()`, `searchDebounceTimer`, `pollIngest()`, `uploadQueue`.
2. **Backend State Mapping**:
   - Trace SQLite schema (`objects`, `kv`, `jobs`, `audit_logs`).
   - Map Telegram backend states: `FakeBackend`, `BotBackend`, `MTProtoBackend`, `BotHarvester`.
3. **Race Condition & Rerender Inventory**:
   - Document DOM recreation overhead in `renderRows()` / `renderGallery()`.
   - Document timer collision in `#fSearch.oninput` vs `#fClear.onclick`.
   - Document concurrent 401 race condition in `refresh()` during `boot()`.

*Phase 1 Acceptance Criteria*:
- Comprehensive state and lifecycle map documented with verified code references.
- All 5 root causes confirmed and mapped to target code locations.

---

### Phase 2 — Selection Reliability & Freeze Elimination
1. **In-Place DOM Selection Updates**:
   - Refactor `toggleSel(id)` to update the DOM element's `.selected` class directly via `document.querySelector(`[data-id="${id}"]`)` or event delegation.
   - Refactor `#selAllBtn.onclick`: iterate through rendered cards/rows, add IDs to `selSet`, toggle `.selected` class, and set `.selbox` checked state in-place. **MUST NOT call `renderRows()` or `renderGallery()`**.
   - Refactor `setSelectMode(false)`: clear `selSet`, remove `.selected` classes, and uncheck `.selbox` checkboxes in-place.
2. **State & Performance Optimization**:
   - Update `updateSelBar()` to use `selSet.size` directly and cache the visible item count, eliminating `visibleFiles()` array filtering on every click.
   - Maintain selection visual integrity across view mode switches (`syncCachedSelection`).
3. **Automated & E2E Testing**:
   - Add unit/browser test in `tests/test_e2e_playwright.py` asserting selection of 100+ files completes without frame drop (<50ms).

*Phase 2 Acceptance Criteria*:
- Selecting single items, selecting all, and deselecting all on a 500-item list causes zero layout rebuilds or page freezing.
- Frame execution times remain under 50ms during rapid selection toggling.

---

### Phase 3 — File Move UX & Safety
1. **Interactive Modal State Machine**:
   - Retain `#moveModal` on screen when the user clicks confirm.
   - Display a spinner and loading message (`"انتقال …"` / `"Moving files..."`) on `#moveOk`.
   - Disable `#moveOk` and `#moveCancel` during network requests to prevent duplicate submissions.
2. **Client-Side Path Validation**:
   - Validate `#moveDest`:
     - If `dest.startsWith(sourceFolder + "/")`, display inline warning: "Cannot move a folder into its own subfolder" and disable submit.
     - If `dest === currentFolder`, display inline warning: "Items already in this destination" and disable submit.
3. **Post-Move Reporting & State Invalidation**:
   - Close modal upon completion.
   - Parse backend move response (`moved`, `skipped`) and show informative toast: `X files moved successfully (Y skipped)`.
   - Evict `folderViewCache`, clear `selSet`, and call `refresh()`.
4. **Keyboard Accessibility**:
   - Trap focus in `#moveModal`, support `Escape` to close (when not in-flight) and `Enter` in `#moveDest` to trigger submission.
5. **E2E Testing**:
   - Add Playwright E2E test verifying move validation, progress spinner visibility, and post-move file list updating.

*Phase 3 Acceptance Criteria*:
- Move modal visibly indicates in-flight progress until backend completion.
- Illegal circular moves are blocked with clear inline error messages.
- View reconciles immediately after move with accurate success counts.

---

### Phase 4 — Media Capability & MKV Detection
1. **Standardized Video Container Configuration**:
   - In `openFileModal()`, configure `<video>` with a nested `<source>` element specifying `type="video/x-matroska"`, `type="video/mp4"`, or `type="video/webm"` based on object metadata.
   - Enable `playsinline`, `controls`, and `preload="metadata"`.
2. **Granular Error Inspection**:
   - Replace simplistic `isMkv` error assumption in `vEl.onerror`.
   - Inspect `vEl.error.code`:
     - `MEDIA_ERR_DECODE` (3) or `MEDIA_ERR_SRC_NOT_SUPPORTED` (4): Display codec incompatibility fallback with direct download button.
     - `MEDIA_ERR_NETWORK` (2): Display network connection retry button instead of false codec warning.
3. **Backend Range & MIME Verification**:
   - Verify that `GET /f/{id}` continues serving `video/x-matroska` with `Accept-Ranges: bytes` and `Content-Disposition: inline`.
4. **Testing**:
   - Verify existing `tests/test_mkv_video_preview.py` passes.
   - Add Playwright test verifying that an MKV file containing H.264/AAC loads directly in Chromium without showing the unsupported banner.

*Phase 4 Acceptance Criteria*:
- MKV files with web-compatible codecs play natively in Chromium without false-positive error banners.
- True codec failures display actionable diagnostic messaging and download options.

---

### Phase 5 — Search Race-Condition Fix
1. **Synchronous Debounce Cancellation**:
   - In `#fClear.onclick`: call `clearTimeout(searchDebounceTimer)`, reset `searchDebounceTimer = null`.
   - In `#fSearch.oninput`: if `e.target.value` is empty, immediately clear `fQuery`, cancel timer, and execute `renderRows()` synchronously.
2. **Cache Invalidation & Atomic Binding**:
   - When search is cleared, invalidate search keys in `folderViewCache` (`evictFolderViewCache()`).
   - Ensure `fQuery` in JavaScript memory and `#fSearch.value` in the DOM cannot diverge.
3. **Testing**:
   - Add regression test simulating typing "query", waiting 30ms, clicking clear, waiting 1000ms, and asserting `#fSearch.value === ""` and full file list remains visible.

*Phase 5 Acceptance Criteria*:
- Zero instances of previously typed search terms reappearing after clearing.
- Rapid typing and clearing cycles remain stable and deterministic.

---

### Phase 6 — Startup & Cold-Restart Initialization
1. **Deterministic Session Verification**:
   - Refactor `boot()` and `showApp()`: ensure session validation completes before firing parallel administrative data requests.
2. **Transparent 401 Re-Login and Retry in `api()`**:
   - In `api(path, opt)`:
     - On HTTP 401, if `_apiKey` is available, initiate `/ui/login` to obtain a fresh session cookie.
     - Use a singleton `reLoginPromise` so concurrent 401s coalesce into a single login request.
     - Upon successful login, **transparently retry the original failed request once** before returning or throwing.
     - If the retry fails, throw the error and transition to `showLogin()`.
3. **Uncoupling SQLite Listings from Telegram Readiness**:
   - Confirm `GET /api/v1/admin/objects` reads strictly from SQLite and returns immediately on startup.
4. **Testing**:
   - Add E2E cold-start test: restart server, navigate directly to dashboard, assert files load on initial render without opening Settings.

*Phase 6 Acceptance Criteria*:
- File dashboard populates on cold start within 1.5 seconds without visiting Settings.
- Transient 401 cookie expirations are automatically and transparently healed on the first request.

---

### Phase 7 — Falkenstein Deployment Continuity
1. **Verify Remote Environment Invariants**:
   - Confirm server is `Falkenstein` (`dl.amiri-dev.ir`).
   - Verify container `anbar-anbar-1` uses `/opt/anbar/compose.yaml` mounting `/opt/anbar/data`, `/opt/anbar/secrets`, `/opt/anbar/.env`.
2. **Local Untracked Deployment Automation**:
   - Maintain a local deployment helper outside Git (e.g. `~/.anbar_deploy.sh` or local untracked script) to perform:
     - Local git check: clean working tree, commit pushed to origin.
     - Remote SSH command: `cd /root/anbar && git pull && docker build -t anbar:prod -f docker/Dockerfile .`
     - Remote container restart: `cd /opt/anbar && docker compose -f compose.yaml up -d`
     - Remote health check: `curl -s http://127.0.0.1:8318/healthz`
     - Production HTTPS check: `curl -s https://dl.amiri-dev.ir/healthz`
3. **Rollback Procedure**:
   - Tag prior stable image before deploy (`anbar:rollback`).
   - Rollback command: `docker tag anbar:rollback anbar:prod && cd /opt/anbar && docker compose -f compose.yaml up -d`.

*Phase 7 Acceptance Criteria*:
- Deployment workflow is fully documented, reproducible, and safeguards production volumes.
- Zero local deployment scripts or credentials committed to Git.

---

### Phase 8 — Comprehensive Verification Strategy
1. **Unit & Integration Suite**:
   - Run `pytest` across all test modules (target: 394+ passing tests).
2. **Playwright E2E Suite**:
   - Run `pytest tests/test_e2e_playwright.py` with expanded tests covering:
     - 100+ file selection performance.
     - File move modal loading spinner and circular path rejection.
     - Search bar clear race condition.
     - Cold start direct file load without opening settings.
     - Native MKV playback.
3. **Code Quality & Linter Checks**:
   - `ruff check src/ tests/`
   - `ruff format --check src/ tests/`
   - `node --check` on `src/anbar/ui/index.html` inline scripts.
4. **Production Smoke Testing**:
   - Health check on `https://dl.amiri-dev.ir/healthz`.
   - File listing and media preview inspection on production.
5. **Documentation Synchronization**:
   - Update `docs/WORKING_RECORD.md`, `CHANGELOG.md`, `docs/API.md`, and `docs/ARCHITECTURE.md`.

*Phase 8 Acceptance Criteria*:
- 100% of unit, integration, and E2E browser tests pass.
- Production smoke test confirms successful deployment on Falkenstein.
- Working record documents completion with evidence.
