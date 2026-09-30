# Tasks: Anbar Stabilization and UX Reliability

**Input**: Design documents from `/specs/001-ux-reliability-stabilization/`  
**Prerequisites**: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/api-contracts.md`, `checklists/stabilization.md`

## Phase 1: Setup & Pre-Flight Validation

- [x] T001 Verify local development environment, Python 3.10+ dependencies, Node.js (`node --check`), and Playwright Chromium installation (`tests/test_e2e_playwright.py`)
- [x] T002 [P] Capture baseline test suite metrics and verify clean test execution across existing 394 tests (`pytest -v`)

---

## Phase 2: Foundational State & Lifecycle Infrastructure

- [x] T003 [P] Implement transparent 401 session re-login and single-request retry in `api()` client (`src/anbar/ui/index.html`)
- [x] T004 [P] Serialize dashboard initialization in `boot()` / `showApp()` before dispatching parallel `/admin/status` and `/admin/objects` calls (`src/anbar/ui/index.html`)
- [x] T005 Verify SQLite object listing endpoint (`GET /api/v1/admin/objects`) independence from Telegram connectivity (`src/anbar/api/admin.py`)

---

## Phase 3: User Story 1 - Freeze-Free File Selection (Priority: P1)

**Goal**: Eliminate synchronous DOM destruction/reconstruction on selection actions so selecting individual items, selecting all, and deselecting all on 500+ files executes in <50ms without main-thread lockups.  
**Independent Test**: Load 100+ files in Chromium via Playwright, toggle "Select All" and "Deselect All", and assert that frame duration is <50ms, selection classes update, and DOM element count remains identical without re-rendering cards.

- [x] T006 [P] [US1] Add automated Playwright benchmark test asserting that selecting all and deselecting all on 100+ items executes in <50ms without dropped frames in `tests/test_e2e_playwright.py`
- [x] T007 [US1] Refactor `toggleSel(id)` to directly mutate `.selected` classes and checkbox states in-place via DOM traversal without full re-render (`src/anbar/ui/index.html`)
- [x] T008 [US1] Refactor `#selAllBtn.onclick` to batch update `.selected` classes and checkboxes on existing DOM elements without invoking `renderRows()` or `renderGallery()` (`src/anbar/ui/index.html`)
- [x] T009 [US1] Refactor `setSelectMode(false)` to clear `selSet` and remove selected DOM classes in-place (`src/anbar/ui/index.html`)
- [x] T010 [US1] Optimize `updateSelBar()` and `updateSelAllBtn()` to use cached visible item counts instead of full array filtering (`src/anbar/ui/index.html`)

---

## Phase 4: User Story 2 - Deterministic Cold Restart & File Loading (Priority: P1)

**Goal**: Guarantee that after process termination or cold container start, navigating directly to the dashboard loads files from SQLite immediately within 1.5 seconds without visiting Settings -> Telegram Auth.  
**Independent Test**: Simulate cold container restart with expired/missing session cookie, load root URL, and assert that files populate automatically on initial render.

- [x] T011 [P] [US2] Add restart and recovery test simulating cold start and direct dashboard navigation in `tests/test_e2e_playwright.py`
- [x] T012 [US2] Update `refresh()` error handler to present a non-destructive retry banner (`#netBanner`) instead of clearing `files = []` on transient network errors (`src/anbar/ui/index.html`)

---

## Phase 5: User Story 3 - Coherent and Safe File Moving UX (Priority: P1)

**Goal**: Deliver a transparent move workflow that displays an in-flight loading spinner, validates destination paths client-side (blocking circular moves), and reports exact moved/skipped counts.  
**Independent Test**: Move files via `#moveModal`, verify that buttons disable and spinner shows during flight, assert circular moves into subfolders are blocked with inline errors, and verify accurate post-move toast feedback.

- [x] T013 [P] [US3] Add automated Playwright tests for move validation (circular move rejection and progress indicator) in `tests/test_e2e_playwright.py`
- [x] T014 [US3] Implement client-side path validation in `openMoveModal()` and `doMove()` preventing moves into self or subfolder paths (`src/anbar/ui/index.html`)
- [x] T015 [US3] Refactor `doMove()` to maintain modal visibility with an active loading spinner and disabled submit buttons during API execution (`src/anbar/ui/index.html`)
- [x] T016 [US3] Update post-move notification to parse backend `moved` and `skipped` counts and display granular feedback toast (`src/anbar/ui/index.html`)
- [x] T017 [US3] Add keyboard accessibility (`Escape` to cancel, `Enter` in input to submit) and focus trapping in move modal (`src/anbar/ui/index.html`)

---

## Phase 6: User Story 4 - Race-Free Search Bar State Synchronization (Priority: P2)

**Goal**: Eliminate the search bar race condition where cleared search strings reappear after a delay, ensuring synchronous timer cancellation and atomic input/memory state binding.  
**Independent Test**: Rapidly type a search query, clear it via button or backspace, wait 1000ms, and assert that input remains strictly empty and full folder contents remain visible.

- [x] T018 [P] [US4] Add automated Playwright regression test verifying that clearing search does not resurrect old search strings in `tests/test_e2e_playwright.py`
- [x] T019 [US4] Update `#fClear.onclick` and backspace clearing in `#fSearch.oninput` to synchronously call `clearTimeout(searchDebounceTimer)` (`src/anbar/ui/index.html`)
- [x] T020 [US4] Invalidate search cache keys in `folderViewCache` on clear to prevent stale DOM restoration (`src/anbar/ui/index.html`)

---

## Phase 7: User Story 5 - Accurate Browser Media Capability & MKV Detection (Priority: P2)

**Goal**: Enable native MKV video playback in browsers supporting Matroska demuxing (e.g. Chromium) and differentiate true codec decode failures from network errors.  
**Independent Test**: Open an MKV file containing H.264/AAC in Chromium; verify native video element playback begins without displaying "امکان پخش فایل MKV در این مرورگر وجود ندارد".

- [x] T021 [P] [US5] Add Playwright test asserting native MKV playback in Chromium in `tests/test_e2e_playwright.py`
- [x] T022 [US5] Configure `<video>` element with `<source type="video/x-matroska">` and format-specific type hints in `openFileModal()` (`src/anbar/ui/index.html`)
- [x] T023 [US5] Inspect `video.error.code` to differentiate between `MEDIA_ERR_DECODE` (codec unsupported) and `MEDIA_ERR_NETWORK` before rendering fallback UI (`src/anbar/ui/index.html`)

---

## Phase 8: User Story 6 - Falkenstein Production Deployment Continuity (Priority: P2)

**Goal**: Provide a reproducible remote deployment workflow that enforces `/opt/anbar` absolute mounts, preserves production data/secrets, and keeps local deployment scripts outside Git.  
**Independent Test**: Inspect Falkenstein remote environment via SSH, verify absolute volume bindings, execute health checks on `https://dl.amiri-dev.ir/healthz`, and verify zero uncommitted secrets in Git.

- [x] T024 [US6] Document production deployment invariants and verification procedures in `docs/DEPLOY.md` (`/opt/anbar` mounts vs local dev)
- [x] T025 [US6] Create local untracked helper script outside Git (e.g. `~/.anbar_deploy.sh`) to automate remote git pull, Docker build, compose restart, and healthcheck verification

---

## Phase 9: Full Regression + E2E + Production Verification + Documentation Closure

**Goal**: Final verification gate validating all 49 checklist items, 100% test pass rate, successful production deployment, and complete documentation synchronization.

- [x] T026 [P] Update `CHANGELOG.md` with Keep a Changelog entries for all stabilization fixes
- [x] T027 [P] Update `AUDIT_COVERAGE.md` with audit status flags for `ui/index.html`
- [x] T028 Run full test suite (`pytest -v`), linters (`ruff check`, `ruff format --check`, `mypy`), and `node --check` on `src/anbar/ui/index.html`
- [ ] T029 Execute remote deployment to Falkenstein and run live smoke tests against `https://dl.amiri-dev.ir/`
- [ ] T030 Update `docs/WORKING_RECORD.md` with final verification results, commit hash, and project closure documentation
