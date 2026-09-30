# Product Quality & Acceptance Checklist: Anbar Overhaul

**Purpose**: Concrete, observable verification checklist for Anbar Product Quality & UX Overhaul, covering visual folder navigation, whole-product design system cohesion, async reliability, and complete user journeys.  
**Created**: 2026-10-01  
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: Reviewer-owned requirements-quality and user-acceptance artifact. Mark an item `[x]` only when the specified observable UX/functional criterion is verified through real browser testing or automated E2E assertion.

---

## 1. Visual Hierarchical Move Workflow (Rejecting CLI/Form Experience)

- [ ] CHK001 **Zero Manual Path Requirement**: Can a user select a file in Root (`/`), click "Move", visually drill down 5 folder levels deep (`a/b/c/d/e/`), and confirm relocation without typing any path characters? [Acceptance, Spec §FR-001]
- [ ] CHK002 **Interactive Breadcrumb Ascension**: In `#moveModal`, does clicking any intermediate breadcrumb segment (e.g. clicking `b` while inside `a/b/c/d/`) immediately ascend the view to that level and expose its child folders? [Coverage, Spec §FR-002]
- [ ] CHK003 **Unambiguous Target Location Display**: Does the move dialog prominently display the currently targeted folder path (e.g. `Target: /media/videos/`) before and during confirmation? [Clarity, Spec §FR-003]
- [ ] CHK004 **Visual Circular Move Disabling**: If a folder being moved has descendants, are that folder and all of its subdirectories visibly rendered as disabled (greyed out with unclickable affordance) inside the move browser? [Completeness, Spec §FR-004]
- [ ] CHK005 **Same-Destination Disabling**: Is the "Move Here" button disabled with clear inline guidance when the browsed location is identical to the item's current parent folder? [Clarity, Spec §FR-004]
- [ ] CHK006 **Empty Folder Navigation**: Can a user navigate into and move items into a newly created, completely empty folder without the picker claiming the folder is missing or unselectable? [Edge Case, Spec §FR-001]
- [ ] CHK007 **Scrollable Directory Lists**: When a directory contains 20+ subfolders, does the move picker provide a smooth, bounded scroll area without overflowing the modal viewport? [UX Quality, Spec §FR-001]
- [ ] CHK008 **Real-Time Folder Search**: Does the folder search box inside the move picker filter visible folder tiles in real-time without re-querying the network? [Performance, Spec §FR-005]
- [ ] CHK009 **Multi-Item Move Header Summary**: When moving multiple selected items, does the dialog header clearly summarize the count and item names without overflowing the title area? [Clarity, Spec §FR-007]
- [ ] CHK010 **In-Flight Progress & Non-Stuck State**: Does the move modal display an active spinner and disable buttons during execution, and on network failure restore interactive buttons with actionable error text? [Reliability, Spec §FR-015]

---

## 2. Whole-Product Design System & Visual Hierarchy

- [ ] CHK011 **Grouped Semantic Toolbars**: Are the 11+ application toolbar buttons grouped into clean, distinct flex clusters (`Primary Ingest`, `View & Sort`, `Batch Actions`) on desktop rather than a single sprawling line? [Consistency, Spec §FR-008]
- [ ] CHK012 **Standardized Control Dimensions**: Do all buttons, selects, and text inputs adhere to standardized heights (36px desktop / 32px mobile) with unified 10px border radius and vertical text alignment? [Consistency, Spec §FR-009]
- [ ] CHK013 **Mobile Responsive Adaptation (<480px)**: On mobile viewports (375px width), do secondary toolbar buttons collapse text labels to clean icon-only buttons with tooltips, preventing multi-row fragmentation? [Coverage, Spec §FR-010]
- [ ] CHK014 **Contextual Empty Directory State**: Does an empty folder display a tailored SVG illustration, friendly title ("این پوشه خالی است"), descriptive hint, and an immediate "Upload Files" shortcut button? [Clarity, Spec §FR-011]
- [ ] CHK015 **Contextual Zero-Search Result State**: Does an unmatched search query display a clean search illustration, title ("نتیجه‌ای یافت نشد"), and a prominent "Clear Search" button? [Clarity, Spec §FR-011]
- [ ] CHK016 **Distinct Destructive Action Styling**: Are irreversible destructive actions (permanent deletion, trash purge, bulk link revocation) styled with prominent red danger buttons (`btn-danger`)? [Consistency, Spec §FR-013]
- [ ] CHK017 **Modal Backdrop & Focus Consistency**: Do all modal dialogs share unified semi-transparent backdrop blur, standardized close button placement, and keyboard `Escape` closing? [Consistency, Spec §FR-012]

---

## 3. Reliability & Asynchronous Lifecycle Resilience

- [ ] CHK018 **Universal Double-Click Guarding**: Does rapidly double-clicking any modal submit button (Create Folder, Rename, Move, Mint Link, Purge) fire exactly one network request and reject concurrent submissions? [Reliability, Spec §FR-014]
- [ ] CHK019 **Zero Infinite Spinners on API Failure**: When an API request times out or returns HTTP 500, does the triggering modal reset its button state, remove spinners, and display an actionable error banner? [Reliability, Spec §FR-015]
- [ ] CHK020 **Deterministic History Navigation**: Does navigating back and forward in browser history between virtual folders (`#folder=...`) update the file listing without losing active view mode or sort selection? [Reliability, Spec §FR-016]
- [ ] CHK021 **Media Resource Teardown on Close**: Does closing the video preview modal immediately pause playback and unload media source buffers, preventing background audio leaks or memory leaks? [Reliability, Spec §FR-017]
- [ ] CHK022 **Authoritative View Refresh on Mutation**: Following folder creation, renaming, or deletion, does the main file tree update authoritatively from the backend without requiring a manual browser reload? [Consistency, Spec §FR-016]

---

## 4. End-to-End Quality & Visual Verification

- [ ] CHK023 **Automated E2E Deep Move Journey**: Is there an automated Playwright test that seeds a 5-level directory structure, executes a move via breadcrumbs without keyboard typing, and asserts authoritative file relocation? [Measurability, Spec §SC-001]
- [ ] CHK024 **Automated E2E Responsive Layout Assertions**: Is there an automated Playwright test that tests viewport widths (1280px and 375px), asserting zero horizontal scroll and verifying that all touch targets measure ≥36px? [Measurability, Spec §SC-003]
- [ ] CHK025 **Automated E2E Rapid Click Stress Test**: Is there an automated Playwright test that executes rapid 5x repeated clicks across search clear, select mode, and folder creation, asserting zero state de-synchronization? [Reliability, Spec §SC-004]
- [ ] CHK026 **Production Deployment Smoke Verification**: Does the production deployment helper verify container health, local 8318 healthz, and public HTTPS healthz on `https://dl.amiri-dev.ir/`? [Traceability, Spec §SC-005]

---

## Notes
- Mark items `[x]` only after empirical verification through automated tests or browser inspection.
- `/speckit-implement` reads checklist state as a gate and does not modify markers.
