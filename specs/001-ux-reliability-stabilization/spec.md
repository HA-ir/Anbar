# Feature Specification: Anbar Stabilization and UX Reliability

**Feature Branch**: `001-ux-reliability-stabilization`  
**Created**: 2026-09-30  
**Status**: Draft  
**Input**: User description: "Create the baseline specification for the current Anbar stabilization and UX reliability work."

---

## Clarifications

### Session 2026-09-30

- Q: How does file selection currently work and what causes main-thread freezing? → A: Selection state is tracked in `selSet`, but `renderRows()` and `renderGallery()` synchronously destroy and recreate the entire DOM tree (up to 500 rows or cards with video/img tags and event listeners) upon Select All, Deselect All, or selectMode toggles, plus `updateSelAllBtn()` runs a full `visibleFiles()` array scan on every click. Clarification: Selection state changes MUST directly toggle `.selected` classes and checkbox `.checked` properties on existing DOM nodes without rebuilding DOM trees or rescanning file arrays.
- Q: How does file movement currently work and why is the UX deficient? → A: `openMoveModal()` displays a text input and folder chips, but `doMove()` immediately closes the modal before starting network requests, provides zero progress feedback during batch updates, and silently treats invalid recursive moves (moving a folder into its own subfolder) as success (`ok++`). Clarification: The move modal MUST remain visible with an active progress spinner and disabled submit buttons during execution, validate destination paths client-side before dispatch, and display exact counts of moved, skipped, and failed items.
- Q: How is file search state synchronized and why do old search strings reappear? → A: `#fSearch.oninput` schedules `renderRows()` via `searchDebounceTimer` (75ms), but `#fClear.onclick` does not clear `searchDebounceTimer`; furthermore, `folderViewCache` caches DOM nodes under compound keys (`viewMode::folder::query::type::sort`), causing race conditions where pending timers or cached DOM restorations re-inject stale search views. Clarification: Clearing search MUST synchronously cancel `searchDebounceTimer`, reset `fQuery` and `#fSearch.value`, invalidate cached search keys, and prevent out-of-order async responses from overwriting the empty state.
- Q: How is media playback capability detected and why is MKV falsely rejected? → A: `openFileModal` unconditionally displays a blanket error banner ("امکان پخش فایل MKV در این مرورگر وجود ندارد") on any video error if `extOf(filename) === "mkv"`, without checking `video.canPlayType`, `MediaCapabilities`, or `video.error` codes. Clarification: Video elements MUST be provided with valid MIME types (`video/x-matroska`, `video/webm`, `video/mp4`), rely on browser demuxing, and inspect `video.error.code` (`MEDIA_ERR_DECODE`, `MEDIA_ERR_SRC_NOT_SUPPORTED`, `MEDIA_ERR_NETWORK`) to distinguish true codec incompatibility from network/Range errors before showing fallback download controls.
- Q: What exact lifecycle causes files to not load on cold restart until Telegram Auth settings are opened? → A: On startup, `showApp()` calls `refresh()` which issues `Promise.all([api("/admin/status"), api("/admin/objects")])` concurrently. When the session cookie is uninitialized or expired, both requests receive a 401 concurrently. `api()` attempts re-login on 401 but still throws on the in-flight request without retrying it, causing `refresh()` to set `files = []` and render an empty screen. Opening Settings -> Telegram Auth issues sequential API calls that successfully re-mint the session cookie, allowing subsequent refreshes to succeed. Clarification: The startup lifecycle MUST ensure session cookie validity before launching parallel data fetches, and `api()` MUST transparently retry the failed request once after a successful re-login before throwing an error.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Responsive and Freeze-Free File Selection (Priority: P1)

As an administrator managing large repositories of files (up to hundreds of objects in active folders), I want to select individual files, ranges of files, or all files seamlessly without experiencing UI freezing, jank, or browser lockups.

**Why this priority**: Page freezing directly impairs basic file management operations (delete, move, share, zip download) and leads to user frustration and unintended double-clicks.

**Independent Test**: Load a folder containing 500 files; toggle single selection, multi-selection, "Select All", and "Deselect All" repeatedly. The browser main thread MUST remain responsive with frame times under 50ms and zero script execution pauses.

**Acceptance Scenarios**:

1. **Given** a directory containing up to 500 files in table or gallery view, **When** the user clicks "Select All", **Then** all visible items reflect selected visual states and checkboxes update within 100ms without rebuilding the DOM tree or reloading media thumbnails.
2. **Given** an active selection of multiple files, **When** the user clicks "Deselect All" or toggles select mode off, **Then** all selected states clear instantly and the selection action bar hides smoothly.
3. **Given** a user rapidly toggling individual file checkboxes or cards, **When** repeated clicks occur, **Then** state transitions remain deterministic with no event storm, no redundant derived-state recalculations, and no memory leakage.
4. **Given** an active search filter or folder prefix, **When** "Select All" is triggered, **Then** only the currently filtered/visible items are selected, and clearing the filter preserves or safely reconciles the selection state according to explicit user actions.

---

### User Story 2 - Deterministic Cold Restart and File Loading (Priority: P1)

As an administrator restarting the Anbar container or starting after a system outage, I want the web interface to load and display all stored files immediately upon opening, without requiring manual navigation into Settings -> Telegram Auth.

**Why this priority**: A storage service that fails to show files upon boot appears broken and forces operational friction, causing false alarms regarding data loss.

**Independent Test**: Stop the Anbar service, restart it cleanly, navigate directly to the root dashboard in a browser, and verify that the file list and storage metrics populate automatically on first render without visiting settings.

**Acceptance Scenarios**:

1. **Given** a freshly restarted server with valid credentials, **When** the user loads the dashboard, **Then** the application performs deterministic session verification and retrieves stored files from SQLite without hanging, error swallowing, or 401 redirect loops.
2. **Given** concurrent initial status and object requests upon boot, **When** a session cookie requires refresh, **Then** session renewal occurs atomically once, preventing concurrent request rejections and blank list states.
3. **Given** a transient delay in Telegram client backend connection readiness, **When** the file metadata view is loaded, **Then** SQLite metadata displays immediately and an unobtrusive background indicator reflects backend connectivity status without blocking file exploration.

---

### User Story 3 - Coherent and Informative File Moving UX (Priority: P1)

As an administrator organizing files, I want a transparent, informative, and accessible move workflow that clearly communicates what is being moved, available destination folders, progress during execution, and definitive success or error feedback.

**Why this priority**: Blind or unconfirmed moves risk data misplacement, user confusion over item whereabouts, and duplicate operations.

**Independent Test**: Select single and multiple files/folders, trigger the move modal, select a destination folder (root, existing, or nested), verify loading indicators during transit, and observe immediate, accurate folder view refresh.

**Acceptance Scenarios**:

1. **Given** one or more selected items (files and/or folders), **When** the user initiates the move action, **Then** a structured modal opens displaying:
   - Summary of items being moved (count, names of single items).
   - Interactive folder browser/chips showing available destinations (including Root).
   - Clear confirmation button disabled until a valid destination different from the source is selected.
2. **Given** an in-flight move operation, **When** execution begins, **Then** the modal displays a non-blocking progress state (spinner/status), prevents duplicate submissions, and remains visible until the operation completes or fails.
3. **Given** an invalid destination (e.g., moving a folder into itself or a subfolder of itself, or moving to the exact same current location), **When** selected, **Then** the UI provides immediate inline validation preventing the illegal move without silent pseudo-success.
4. **Given** a successful move operation, **When** the backend completes the update, **Then** the modal closes, a descriptive toast confirms the count of moved items, the folder cache invalidates, and the view updates immediately to reflect the new hierarchy.

---

### User Story 4 - Race-Free Search Bar State Synchronization (Priority: P2)

As an administrator searching for specific files, I want the search input to remain completely stable when typed in or cleared, without old search terms mysteriously reappearing after a delay.

**Why this priority**: Search term reappearance breaks muscle memory, disrupts user navigation, and forces repetitive manual deletions.

**Independent Test**: Type a search query, wait for results to filter, click the clear button ("×") or select all and delete, wait 5 seconds, and verify that the input remains empty and full folder contents remain displayed.

**Acceptance Scenarios**:

1. **Given** an active search query in the search bar, **When** the user clicks the clear button or deletes all text, **Then** the local input, internal query state, and view filter clear synchronously and permanently.
2. **Given** in-flight debounced render timers or background refresh responses, **When** the user clears the search bar, **Then** pending timers are canceled and stale asynchronous responses are invalidated, preventing resurrection of superseded search strings.
3. **Given** browser navigation (Back/Forward) or URL parameter changes, **When** history changes occur, **Then** search state synchronizes deterministically with history state without recursive input overwrites.

---

### User Story 5 - Accurate Browser Media Capability & MKV Detection (Priority: P2)

As a user viewing video files stored in Matroska (.mkv) containers, I want the browser to play videos directly whenever the browser possesses container and codec decoding support, rather than seeing an unconditional failure banner.

**Why this priority**: Modern Chromium and desktop browsers natively support MKV containers containing H.264, VP9, or AV1 video; falsely rejecting playback degrades UX and forces unnecessary multi-gigabyte downloads.

**Independent Test**: Open an MKV file encoded with H.264/AAC in a Chromium browser; the video element MUST initialize playback directly. In browsers genuinely lacking codec support, the fallback message MUST specify the exact technical reason and offer a one-click download.

**Acceptance Scenarios**:

1. **Given** an MKV file whose video and audio streams are supported by the browser, **When** the file modal opens, **Then** the player mounts with appropriate MIME type configuration (`video/x-matroska`, `video/webm`, or detected container) and streams content smoothly via HTTP Range requests.
2. **Given** an MKV file containing codecs genuinely unsupported by the client browser (e.g., legacy MPEG-2, DTS audio in Firefox), **When** decoding fails, **Then** the application distinguishes between network errors and decode errors, displaying an educational diagnostic message with a primary "Download Video" call to action.
3. **Given** video preview generation in the main gallery, **When** media cards render, **Then** capability detection and poster generation operate without crashing or spamming console errors.

---

### User Story 6 - Reproducible Local-to-Remote Deployment Continuity & Records (Priority: P2)

As a maintainer developing on a local laptop (`/home/hossein/Projects/Anbar`) and deploying to production (`Falkenstein:/root/anbar`), I want a clearly documented, reproducible deployment procedure and up-to-date working records so any session can inspect, deploy, or resume work with zero configuration drift.

**Why this priority**: Prevents critical production incidents (such as BUG-37 volume misdirection) and ensures multi-session engineering continuity.

**Independent Test**: Verify that local development files, environment templates, and documentation adhere to isolation rules, and that `docs/WORKING_RECORD.md` maintains a complete audit trail of objectives, changes, and verification states.

**Acceptance Scenarios**:

1. **Given** code changes verified locally, **When** preparing for deployment, **Then** all deployment commands strictly target `/opt/anbar` with absolute persistent volume paths (`/opt/anbar/data`, `/opt/anbar/secrets`, `/opt/anbar/.env`).
2. **Given** local deployment scripts or credentials, **When** inspecting the git status, **Then** zero deployment credentials or server automation helpers are tracked in Git.
3. **Given** the conclusion of any engineering session, **When** the session ends, **Then** `docs/WORKING_RECORD.md` records the exact current commit, test counts, verified capabilities, and next action.

---

### Edge Cases

- **Large Selection Under Filtering**: What happens if 500 files are selected, a search filter is applied showing only 2 files, and "Delete Selected" is clicked? The confirmation modal MUST explicitly state how many items are being affected (all 500 vs. 2 filtered) to prevent accidental data loss.
- **Deeply Nested Folder Moves**: Moving a folder `/a/b/c/` into `/a/b/` must be correctly identified as a no-op or valid rename, whereas moving `/a/` into `/a/b/c/` must be strictly forbidden due to cyclical path recursion.
- **MKV Audio Codec Incompatibility**: A video stream may decode cleanly (H.264) while the audio track (e.g. AC3/DTS) is silent or causes media errors in certain browsers. The player must detect decode failure gracefully without hanging the modal.
- **Rapid Search Clear/Type Races**: A user types "abc", rapidly clears, then types "xyz" within the 75ms debounce window. The final state MUST filter strictly on "xyz" with zero intermediate flicker of "abc".
- **Restart with Network Partition**: If the server restarts while the host network to Telegram is temporarily degraded, the web UI must still serve cached SQLite file listings with a clear indicator that background uploads/downloads are queuing or awaiting connectivity.

---

## Requirements *(mandatory)*

### Functional Requirements

#### File Selection Performance & Architecture (Area A)
- **FR-001**: The UI selection architecture MUST NOT rebuild, re-render, or destroy DOM elements (`renderRows()` / `renderGallery()`) merely to toggle selection states on items.
- **FR-002**: Selection visual states (e.g., `.selected` class on rows and cards, checkbox `.checked` property) MUST be updated via direct targeted DOM manipulation or event delegation.
- **FR-003**: The "Select All" operation MUST compute target IDs without invoking full list re-sorting, folder tree re-aggregation, or redundant storage size recalculations.
- **FR-004**: Multi-selection bar updates (`updateSelBar`) MUST use cached item counts and avoid full-table scans on every single item selection change.
- **FR-005**: Selection state (`selSet`) MUST remain consistent across view mode switches (Table vs. Gallery) without state loss or memory leaks.
- **FR-006**: When items are deleted or moved, `selSet` MUST be pruned immediately to prevent ghost selections.

#### File Moving UX (Area B)
- **FR-007**: The file moving modal MUST clearly display the names or summary count of all items targeted for relocation.
- **FR-008**: Destination selection MUST provide a clear choice between Root (`/`), existing folder paths, and the ability to specify a new destination folder.
- **FR-009**: The UI MUST validate destination paths client-side before submission, preventing illegal moves (moving a folder into its own sub-tree or moving an item into its current location).
- **FR-010**: During move execution, the move modal MUST present an active loading/progress state and disable submission controls to prevent duplicate API requests.
- **FR-011**: The move workflow MUST provide granular feedback upon completion, detailing how many items succeeded and identifying any skipped or failed items.
- **FR-012**: Upon successful completion, the folder view cache (`folderViewCache`) MUST be invalidated, the active selection cleared, and the view refreshed to reflect the new hierarchy.
- **FR-013**: The move interface MUST be fully accessible via keyboard (`Escape` to cancel, `Enter` to confirm, focus trapped within modal while open).

#### MKV & Media Playback Detection (Area C)
- **FR-014**: The media player component MUST NOT assume all `.mkv` files are unplayable based solely on file extension.
- **FR-015**: The application MUST configure `<video>` elements with standard MIME types and codecs where known, supporting container playback across browsers that support Matroska.
- **FR-016**: The media player MUST inspect `video.error` codes (`MEDIA_ERR_SRC_NOT_SUPPORTED`, `MEDIA_ERR_DECODE`, `MEDIA_ERR_NETWORK`) to distinguish between missing codec support, corrupted data, and network connection drops.
- **FR-017**: When media playback genuinely fails due to unsupported codecs, the UI MUST render an informative fallback specifying container/codec incompatibility alongside a direct download button.
- **FR-018**: The backend MUST continue serving video requests with correct headers (`Content-Type: video/x-matroska`, `Accept-Ranges: bytes`, and 206 Partial Content support).

#### Search Bar State Synchronization (Area D)
- **FR-019**: Clearing the search bar via the clear button ("×"), Backspace, or text selection MUST immediately set the active filter query (`fQuery`) to empty.
- **FR-020**: Any pending debounced search timer MUST be canceled immediately upon input clearing.
- **FR-021**: The UI MUST prevent background refresh cycles or cached view restorations from re-populating the search input with stale query strings.
- **FR-022**: Search input state (`#fSearch.value`) and memory state (`fQuery`) MUST remain synchronized at all times.

#### Cold Restart & Deterministic Initialization (Area E)
- **FR-023**: Application startup MUST initialize database connections, runtime configuration, and web authentication secrets deterministically prior to accepting client traffic.
- **FR-024**: Dashboard file listing requests (`GET /api/v1/admin/objects`) MUST depend solely on local SQLite database state and MUST NOT block or fail if the Telegram backend connection is in-flight.
- **FR-025**: The web client boot sequence (`boot()` / `showApp()`) MUST serialize session authentication verification before issuing concurrent administrative API calls.
- **FR-026**: If a stored admin API key exists, session cookie renewal MUST occur atomically without triggering false 401 logouts or empty file states.
- **FR-027**: Opening the Settings drawer or Telegram Auth panel MUST NOT be required for the application to achieve fully operational file browsing capability.

#### Deployment Continuity & Records (Area F & G)
- **FR-028**: Production deployment procedures MUST strictly utilize absolute volume mappings on the remote host (`/opt/anbar/data`, `/opt/anbar/secrets`, `/opt/anbar/.env`) and compose commands executed from `/opt/anbar`.
- **FR-029**: Local helper deployment scripts and credentials MUST remain strictly untracked and outside the Git repository.
- **FR-030**: Every engineering iteration MUST maintain synchronization across `docs/WORKING_RECORD.md`, `CHANGELOG.md`, `docs/API.md`, `docs/ARCHITECTURE.md`, `BUGS_AND_FIXES.md`, and `AUDIT_COVERAGE.md`.

---

### Key Entities

- **FileObject**: Represents a stored file or folder marker in Anbar. Attributes include `id` (unique string), `filename` (path string), `size` (bytes), `content_type` (MIME string), `created_at` (timestamp), `hasThumb` (boolean), `downloaded` (integer count).
- **SelectionState**: Represents active user selections in the UI. Attributes include `selSet` (Set of object IDs), `selectMode` (boolean flag), `activeCount` (integer).
- **MoveRequest**: Encapsulates a relocation instruction. Attributes include `sourceIds` (array of string IDs), `destinationFolder` (normalized string prefix), `dryRun` (boolean validation flag).
- **MediaCapabilitiesReport**: Encapsulates client decoding capability. Attributes include `containerSupported` (boolean), `codecSupported` (boolean), `directPlayViable` (boolean), `errorCode` (integer or null).

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Toggling selection state on any individual item or clicking "Select All" / "Deselect All" on a 500-item folder completes in under 50ms without dropping frames or triggering full DOM rebuilds.
- **SC-002**: Cold restart of the Anbar service displays stored files on initial browser navigation within 1.5 seconds, with 0% dependency on opening the Settings modal.
- **SC-003**: 100% of illegal move operations (moving into self, cyclical paths, or redundant moves) are caught and flagged by client-side validation prior to network dispatch.
- **SC-004**: During file moves, 100% of operations display continuous progress feedback until complete, followed by immediate folder view reconciliation.
- **SC-005**: Clearing the search input results in 0 occurrences of old search terms reappearing across 100 consecutive clear/search cycles.
- **SC-006**: Compatible MKV video files (e.g. H.264/AAC in Chromium) start playback within 1 second of modal opening without displaying false incompatibility banners.
- **SC-007**: 100% of all user-facing changes are covered by automated unit/integration tests and verified via Playwright E2E browser tests.
- **SC-008**: 100% of production deployment instructions adhere to verified absolute path isolation with zero secret leakage into Git.

---

## Assumptions

1. **Browser Capabilities**: Modern browsers (Chrome, Edge, Opera, newer Firefox) natively support Matroska container playback with standard Web-compatible codecs (H.264, VP9, AV1, Opus, AAC); browsers lacking MKV container demuxing will gracefully trigger the standardized fallback download UI.
2. **Folder Structure**: Folders in Anbar are virtual path prefixes represented in SQLite filenames (e.g. `documents/2026/report.pdf`) and optional zero-byte directory markers ending with `/`. Moving items operates via filename prefix updates.
3. **Authentication Strategy**: Administrative web access relies on HttpOnly session cookies minted from the admin API key, with Bearer header fallback for direct API calls.
4. **Local/Remote Separation**: Development commands execute on the local Linux host; deployment execution targets Falkenstein Docker container `anbar-anbar-1` mounted to `/opt/anbar`.
