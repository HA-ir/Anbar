# Tasks: Anbar Product Quality & UX Overhaul

**Input**: Design documents from `/specs/002-ux-product-overhaul/`  
**Prerequisites**: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/ui-contracts.md`, `checklists/acceptance.md`

## Phase 1: Setup & Pre-Flight Verification

- [x] T001 Verify active testing environment, Playwright browser instances, and baseline test suite (`pytest -v`)
- [x] T002 [P] Capture baseline screenshots for desktop and mobile viewports (`tests/test_e2e_playwright.py`)

---

## Phase 2: Foundational Design Tokens & State Infrastructure

- [x] T003 [P] Add standardized CSS design tokens to `:root` in `src/anbar/ui/index.html` (`--btn-h: 36px`, `--btn-h-sm: 30px`, `--btn-radius: 10px`, spacing tokens `--sp-xs` through `--sp-lg`)
- [x] T004 [P] Implement universal modal submit guard wrapper `guardModalSubmit()` in `src/anbar/ui/index.html` to eliminate double-submit races and stuck loading states

---

## Phase 3: User Story 1 - Interactive Hierarchical Move Workflow (Priority: P1) 🎯 MVP

**Goal**: Transform the Move modal from a raw text path input into an interactive virtual folder browser with breadcrumb navigation, child directory drill-down, and visual circular move disabling.  
**Independent Test**: Seed a 5-level directory structure (`a/b/c/d/e/`). Select a file, open the move modal, drill down into `a/b/c/d/e/`, ascend back to `a/b/` via breadcrumb click, and confirm relocation with zero keyboard typing.

- [x] T005 [P] [US1] Add automated Playwright E2E test `test_hierarchical_move_browser_navigation` asserting 5-level visual drill-down and breadcrumb ascension in `tests/test_e2e_playwright.py`
- [x] T006 [US1] Redesign `#moveModal` DOM structure with breadcrumb bar, scrollable child folder viewport, and target location indicator in `src/anbar/ui/index.html`
- [x] T007 [US1] Implement `renderMoveBrowser()` in `src/anbar/ui/index.html` to dynamically extract and render immediate child folders for the active `moveBrowsePrefix`
- [x] T008 [US1] Implement click-to-drill-down on folder tiles and click-to-ascend on breadcrumbs in `src/anbar/ui/index.html`
- [x] T009 [US1] Visually disable circular destinations (greyed out with unclickable styling) for folders being moved and their descendants in `src/anbar/ui/index.html`
- [x] T010 [US1] Add collapsible "Advanced / Manual Path" input toggle for power users in `src/anbar/ui/index.html`
- [x] T011 [US1] Bind "Move Here" button directly to `moveBrowsePrefix`, display active in-flight spinner, disable controls, and refresh view upon success in `src/anbar/ui/index.html`

---

## Phase 4: User Story 2 - Whole-Product Design System & Visual Polish (Priority: P1)

**Goal**: Eliminate visual clutter by reorganizing the flat 11-control toolbar into 3 semantic flex clusters, standardizing button dimensions, and creating purposeful empty states.  
**Independent Test**: Render the UI at desktop (1280px) and mobile (375px). Assert toolbar buttons align into distinct functional groups with uniform 36px/30px heights, and verify empty directories render tailored SVG illustrations with action shortcuts.

- [x] T012 [P] [US2] Add Playwright layout assertions for grouped toolbar alignment and mobile touch target dimensions (≥36px) in `tests/test_e2e_playwright.py`
- [x] T013 [US2] Restructure `.toolbar` in `src/anbar/ui/index.html` into semantic flex groups (`.toolbar-group-primary`, `.toolbar-group-view`, `.toolbar-group-actions`)
- [x] T014 [US2] Standardize button paddings, heights (36px default / 30px compact), and icon alignments across all UI buttons in `src/anbar/ui/index.html`
- [x] T015 [US2] Redesign empty directory (`#empty`) and zero search result (`#noMatch`) states with tailored SVG illustrations and action buttons in `src/anbar/ui/index.html`
- [x] T016 [US2] Apply distinct red styling (`btn-danger`) to all destructive action buttons (purge trash, delete confirmation, revoke all links) in `src/anbar/ui/index.html`

---

## Phase 5: User Story 3 - Comprehensive Journey Audit & Reliability Hardening (Priority: P2)

**Goal**: Harden all async mutating operations (folder creation, renaming, link minting, trash purge) against network latency and duplicate submissions.  
**Independent Test**: Simulate 500ms network delay; rapidly double-click folder creation, renaming, and link minting buttons. Verify that exactly one API call executes, loading spinners appear, and modals fail/succeed gracefully without locking up.

- [x] T017 [P] [US3] Add automated Playwright stress test verifying double-click rejection and spinner activation across modal actions in `tests/test_e2e_playwright.py`
- [x] T018 [US3] Integrate `guardModalSubmit()` into folder creation (`#newFolderBtn`) and renaming (`renameObj`) in `src/anbar/ui/index.html`
- [x] T019 [US3] Integrate `guardModalSubmit()` into link minting options modal (`#shareOptsOk`) in `src/anbar/ui/index.html`
- [x] T020 [US3] Ensure media playback modal cleanly pauses video and disconnects sources upon `#fmClose` in `src/anbar/ui/index.html`
- [x] T021 [US3] Add responsive media queries in `src/anbar/ui/index.html` collapsing secondary toolbar text labels into icon tooltips on narrow viewports (<480px)

---

## Phase 6: Documentation & Persistent Project Records

- [x] T022 [P] Document visual folder navigation contracts and design tokens in `docs/ARCHITECTURE.md`
- [x] T023 [P] Update `CHANGELOG.md` with Keep a Changelog entries for v0.15.58 Product Quality & UX Overhaul
- [x] T024 [P] Update `AUDIT_COVERAGE.md` marking overhauled UI modules and journeys
- [x] T025 [P] Update `BUGS_AND_FIXES.md` with UX audit resolutions and performance benchmarks

---

## Phase 7: Full Product Quality Verification & Production Deployment Closure

**Goal**: Full-system verification gate validating all 26 acceptance checklist items, 100% test pass rate, successful Falkenstein deployment, and live production smoke tests.

- [x] T026 Run full automated test suite (`pytest -v`), Playwright E2E suite (`pytest tests/test_e2e_playwright.py`), and linters (`ruff check`, `ruff format --check`, `mypy`)
- [x] T027 Validate JavaScript syntax in `src/anbar/ui/index.html` via `node --check`
- [x] T028 Bump version to `0.15.58` across `pyproject.toml`, `src/anbar/__init__.py`, and `uv.lock`
- [ ] T029 Execute remote production deployment to Falkenstein via `/home/hossein/anbar_deploy_falkenstein.sh` and perform live smoke tests on `https://dl.amiri-dev.ir/`
- [ ] T030 Update `docs/WORKING_RECORD.md` with final verification evidence, screenshots, deployed commit hash, and milestone completion closure
