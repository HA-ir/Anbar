# Implementation Plan: Anbar Product Quality & UX Overhaul

**Branch**: `002-ux-product-overhaul` | **Date**: 2026-09-30 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-ux-product-overhaul/spec.md`

## Summary

This plan provides an evidence-based technical implementation blueprint to elevate Anbar into a professional, finished product through:
1. **Interactive Hierarchical Move Browser**: Replacing raw text paths with a navigable folder browser featuring child drill-down, breadcrumb ascension, real-time folder search, and visual circular move prevention.
2. **Design System & Visual Hierarchy**: Standardizing control clusters, uniform button heights (36px/32px), unified spacing tokens, responsive mobile flex wrapping, and cohesive modal dialogs.
3. **Universal Async Guarding & Progress States**: Applying atomic loading spinners and button disabling across all mutating modals (folder creation, renaming, moving, link minting, purge).
4. **Contextual Empty States**: Introducing engaging SVG illustrations and actionable shortcuts for empty directories and zero-match search queries.
5. **E2E Browser & Mobile Verification**: Validating all journeys via Playwright automated browser tests across desktop and mobile viewports.

---

## Technical Context

**Language/Version**: Python 3.10+ (Backend), Vanilla JavaScript (ES2022+ / HTML5 in `src/anbar/ui/index.html`)  
**Primary Dependencies**: FastAPI, Uvicorn, SQLite3 (WAL mode), Telethon (MTProto), Pillow  
**Storage**: SQLite database (`/opt/anbar/data/anbar.db`), Telegram cloud  
**Testing**: `pytest`, `pytest-asyncio`, `playwright` (headless Chromium desktop & mobile)  
**Target Platform**: Linux (Development laptop & Falkenstein VPS production)  
**Project Type**: Web application & Telegram-backed object storage gateway  
**Constraints**: Zero local file retention, vanilla JS in single-file UI (`index.html`), zero secret leakage in Git, absolute mount paths (`/opt/anbar`)

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Principle I (Correctness over superficial patching)**: PASS. Replaces CLI-like parameter typing with genuine hierarchical state navigation.
- **Principle II (Root-cause fixes over symptom suppression)**: PASS. Resolves async duplicate submission vulnerabilities through universal button guards.
- **Principle III & IV (User-facing tests & E2E verification)**: PASS. All user-facing layout and navigation changes verified with automated Playwright browser tests on both desktop and mobile viewports.
- **Principle VI (Race-safe asynchronous state)**: PASS. Atomic button guards eliminate double-submit races during folder creation and relocation.
- **Principle XI, XII & XIII (Deployment reproducibility & secrets protection)**: PASS. Production deployments strictly adhere to `/opt/anbar` volume invariants.

---

## Project Structure

### Documentation (this feature)

```text
specs/002-ux-product-overhaul/
├── plan.md              # This implementation plan
├── research.md          # Architecture choices and design rationale
├── data-model.md        # Entities, states, and tokens
├── quickstart.md        # Runnable validation scenarios
├── contracts/           # UI and client state machine contracts
│   └── ui-contracts.md
└── checklists/          # Quality and requirements checklists
    └── requirements.md
```

### Source Code Paths

```text
src/anbar/
├── ui/
│   └── index.html       # Primary UI: move modal redesign, grouped toolbars, empty states, CSS tokens
tests/
└── test_e2e_playwright.py       # Playwright E2E browser journeys (desktop & mobile)
```

---

## Detailed Implementation Phases

### Phase 1 — Move Workflow Redesign (Visual Hierarchical Navigation)
1. **Move Browser State & DOM Structure**:
   - In `src/anbar/ui/index.html`, redesign `#moveModal`:
     - Header: Display items being moved (`moveSub`).
     - Breadcrumb Bar: Navigable breadcrumb trail (`#moveBreadcrumb`).
     - Search Input: Folder filter input (`#moveFilterInp`).
     - Folder Viewport: Scrollable list/grid of direct child folders (`#moveFolderList`).
     - Target Indicator: Current destination badge (`#moveTargetBadge`).
     - Action Bar: Advanced manual path toggle, Cancel button, "Move Here" button (`#moveOk`).
2. **Navigation Interaction Logic**:
   - `renderMoveBrowser()`: Computes direct child folder segments of `currentBrowsePrefix`.
   - Click child folder → drills down (`currentBrowsePrefix = childPath`), updates breadcrumb, re-renders.
   - Click breadcrumb segment → ascends to that ancestor path.
   - Circular validation: Folders matching source paths or their descendants are rendered with `.disabled` styling and are unclickable.
3. **Confirmation & Progress Execution**:
   - "Move Here" binds directly to `currentBrowsePrefix`.
   - Disables controls, displays spinner, executes move API, closes on completion, shows toast, refreshes file list.

*Phase 1 Acceptance Criteria*:
- Users can visually navigate to a folder 5 levels deep without typing any path characters.
- Circular moves are visually blocked in the folder browser.
- Playwright E2E test passes verifying visual navigation and move execution.

---

### Phase 2 — Universal Async Guarding & Reliability Fixes
1. **Modal Submit Guarding**:
   - Apply button disabling and active loading spinner to `#newFolderBtn` modal, `#renameObj` modal, and `#shareOptsOk` modal.
   - Reject secondary clicks while requests are in flight.
2. **Graceful Error Recovery**:
   - Ensure all API catch blocks reset buttons to active state, display descriptive error banners or toasts, and avoid leaving modals in stuck loading states.

*Phase 2 Acceptance Criteria*:
- Rapid double-clicks on any modal action trigger exactly one network request.
- Simulating network failures leaves all controls interactive and displays actionable error messages.

---

### Phase 3 — Information Architecture & Toolbar Reorganization
1. **Semantic Flex Grouping**:
   - In `src/anbar/ui/index.html`, restructure `.toolbar`:
     - Group 1 (Primary Ingestion): `#uploadToggleBtn`, `#pasteBtn`.
     - Group 2 (View & Filter): `#viewBtn`, `#fType`, `#fSort`.
     - Group 3 (Management Actions): `#selectModeBtn`, `#selAllBtn`, `#newFolderBtn`, `#trashBtn`, `#linksBtn`, `#refBtn`.
2. **Standardized Control Dimensions**:
   - Define CSS custom properties: standard button height `36px`, compact height `30px`, uniform padding `8px 12px`, border radius `10px`.
   - Align text baseline and vertical centering across all buttons and selects.

*Phase 3 Acceptance Criteria*:
- Toolbar displays as balanced, distinct control groups on desktop without staggered vertical heights.

---

### Phase 4 — Contextual Empty States
1. **Visual Empty State Components**:
   - Redesign `#empty` (empty directory) and `#noMatch` (zero search results):
     - Empty folder: Clean SVG folder illustration, title ("این پوشه خالی است"), description ("فایل‌های خود را به اینجا بکشید یا دکمه آپلود را بزنید"), primary action button ("آپلود فایل").
     - Zero search results: Search SVG icon, title ("نتیجه‌ای یافت نشد"), description ("فایلی مطابق با عبارت جستجو پیدا نشد"), action button ("پاک کردن جستجو").

*Phase 4 Acceptance Criteria*:
- Navigating to an empty directory or entering an unmatched query displays rich contextual empty states with operational action buttons.

---

### Phase 5 — Responsive Mobile Usability & Accessibility
1. **Mobile Breakpoint Optimization (<480px)**:
   - Implement media queries:
     - Collapse secondary button text labels (`data-i18n`) on narrow screens to icon-only buttons with tooltips (`aria-label`).
     - Enable full-width search bar on its own row.
     - Increase mobile touch targets to minimum 36px/40px footprint.
2. **Keyboard Focus & Accessibility**:
   - Add focus trap and `Escape` support across all modals.
   - Ensure clear focus rings on keyboard tab navigation.

*Phase 5 Acceptance Criteria*:
- Mobile layout (375px) renders without horizontal scroll or broken button wrapping.
- All interactive controls accessible via keyboard tab navigation.

---

### Phase 6 — E2E Browser Testing & Production Verification
1. **Playwright E2E Tests**:
   - `test_hierarchical_move_browser`: Automated journey navigating 3+ folder levels deep via breadcrumbs in the move dialog and verifying item relocation.
   - `test_responsive_toolbar_and_empty_states`: Desktop and mobile viewport assertions.
2. **Production Deployment & Verification**:
   - Deploy v0.15.58 to Falkenstein via `/home/hossein/anbar_deploy_falkenstein.sh`.
   - Perform live smoke tests on `https://dl.amiri-dev.ir/`.
3. **Documentation Closure**:
   - Update `docs/WORKING_RECORD.md`, `CHANGELOG.md`, and `AUDIT_COVERAGE.md`.
