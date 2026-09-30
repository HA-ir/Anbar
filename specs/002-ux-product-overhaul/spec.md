# Feature Specification: Anbar Product Quality & UX Overhaul

**Feature Branch**: `002-ux-product-overhaul`  
**Created**: 2026-09-30  
**Status**: Draft  
**Input**: User description: "Create a new Spec Kit specification for an Anbar 'Product Quality & UX Overhaul' milestone."

---

## Clarifications

### Session 2026-09-30

- Q: What are the exact behavioral gaps in the current file move workflow? → A: In `src/anbar/ui/index.html` lines 3848-3884, `#moveChips` extracts folder prefixes by splitting filenames of existing objects. When a folder path is empty or deeply nested without objects directly inside intermediate paths (e.g. `media/videos/movies/2026`), the chip generation only displays prefixes from loaded objects; clicking a chip merely overwrites the input text value (`d.value = fld`), without drilling down or exposing deeper subdirectories. The user is forced to manually type `/movies/2026`. Clarification: The move modal must maintain an active browsing state (`moveBrowsePrefix`), render a visual list of child folders for that prefix, provide click-to-enter and click-to-ascend breadcrumbs, and bind the confirmation action directly to `moveBrowsePrefix`.
- Q: How should empty directories and deep virtual paths be discovered by the move browser? → A: The backend stores virtual directory markers as objects ending with `/` and aggregates prefixes via `/api/v1/admin/objects`. To prevent the move browser from only showing populated prefixes, the browser must construct a unified client-side directory tree combining explicit directory markers (`folder:...`) and virtual prefixes from loaded objects, enabling navigation into empty folders.
- Q: What are the primary visual inconsistencies in the toolbar layout? → A: On desktop (1280×800), the toolbar renders 11 disconnected buttons, badges, and selects in a single wrap container, producing irregular vertical alignments. On mobile (<480px), the controls fracture across 4 uneven rows. Clarification: Toolbar controls must be partitioned into 3 cohesive flex groups (`.toolbar-group-primary`, `.toolbar-group-view`, `.toolbar-group-actions`) with standardized 36px/30px button heights and responsive label collapsing on narrow viewports.
- Q: How does the application handle async errors and loading states across user journeys? → A: Folder creation, renaming, and link generation presently execute via standard `api()` calls, but several modals lack active button-disabling or visual spin feedback during network flight, allowing rapid duplicate clicks. Clarification: All mutating modals (folder creation, rename, move, link generation, delete confirmation) must adopt the guard pattern (`guardBtn`) or in-place button loading states, rejecting concurrent submissions.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Interactive Hierarchical Folder Navigation for Moving Items (Priority: P1)

As an administrator managing deep or complex directory structures, I want to relocate files and folders using an interactive, visual folder browser within the move dialog so that I can explore nested paths, navigate parent/child directories, inspect breadcrumbs, and choose a destination without ever typing a raw path string.

**Why this priority**: The current move modal requires users to manually type nested directory paths (e.g. `media/videos/movies/2026`), turning basic file organization into an error-prone, developer-like CLI interaction.

**Independent Test**: Create a folder hierarchy 5 levels deep (`a/b/c/d/e/`). Select a file in the root folder, trigger the move modal, visually click into each subfolder down to level 5, navigate back up two levels via breadcrumbs, and confirm the move. Verify the file lands in `a/b/c/` without any keyboard typing.

**Acceptance Scenarios**:

1. **Given** one or more selected files or folders, **When** the move action is initiated, **Then** a modal opens displaying:
   - A summary header stating the exact items being moved (single name or item count).
   - An interactive folder tree/browser displaying Root (`/`) and all direct subdirectories in the current browsing context.
   - Interactive breadcrumbs displaying the path currently navigated inside the picker.
   - Clear visual indicators of the currently highlighted/selected target folder.
   - A disabled "Move Here" button if the selected destination is identical to the item's source location or an illegal descendant.
2. **Given** a nested folder structure, **When** the user clicks on a directory entry in the move browser, **Then** the view descends into that directory, updating the breadcrumb trail and listing its child folders.
3. **Given** a directory containing a folder being moved, **When** browsing destinations, **Then** that folder and all of its descendants are clearly flagged as disabled/inaccessible, preventing circular move attempts before any action is confirmed.
4. **Given** an active move operation, **When** the user clicks "Move Here", **Then** the dialog presents an in-place loading state, disables navigation and action buttons, executes the move, closes upon success, shows a clear completion toast, and authoritatively updates the parent file list.
5. **Given** advanced power users who prefer text input, **When** expanding an "Advanced / Custom Path" toggle, **Then** a manual text input is available as a fallback without cluttering the primary visual navigation.

---

### User Story 2 - Cohesive, Professional Visual Design System (Priority: P1)

As a daily user of Anbar, I want a clean, unified visual hierarchy with consistent typography, balanced spacing, cohesive icon buttons, and non-cluttered toolbars on desktop and mobile so that the interface feels like a finished product rather than an internal debug console.

**Why this priority**: Visual clutter, misaligned buttons, cramped mobile toolbars, and inconsistent affordances degrade user trust, making the application feel unpolished.

**Independent Test**: Audit and render the application at 1280×800 (desktop) and 375×667 (mobile). Verify that toolbars do not wrap into fragmented multi-line button stacks, buttons share standardized padding/heights, and visual hierarchy cleanly separates search, view options, and content.

**Acceptance Scenarios**:

1. **Given** the main files toolbar on desktop or mobile, **When** viewing controls, **Then** buttons are logically grouped into semantic clusters:
   - Primary Creation & Ingestion (`Upload / Ingest` group).
   - View & Organization controls (`Gallery/Table Toggle`, `Folder Navigation`, `Type Filter`, `Sort`).
   - Management & Auxiliary actions (`Select Mode`, `Links Manager`, `Trash`, `Settings`).
2. **Given** mobile viewport dimensions (320px–480px width), **When** viewing the interface, **Then** controls wrap cleanly without horizontal overflow, touch targets adhere to a minimum 40×40px footprint, and action labels collapse to intuitive icons where space is constrained.
3. **Given** empty directories or zero-search result states, **When** rendered, **Then** the UI presents a purposeful empty state illustration with contextual guidance (e.g. "No files found matching 'xyz' — Clear Search" or "This folder is empty — Drop files to upload").
4. **Given** high-contrast and soft light/dark themes, **When** switching themes, **Then** all surfaces, modals, badges, and borders transition smoothly with zero harsh white flashes or illegible text tokens.

---

### User Story 3 - Comprehensive Journey Audit & Error Resilience (Priority: P2)

As an administrator performing routine operations (uploading, renaming, creating folders, managing links, toggling settings, streaming media), I want every workflow to handle network latency, retries, and errors gracefully so that the interface never hangs, locks up, or provides misleading success signals.

**Why this priority**: "Works sometimes" behavior destroys confidence; async actions must be atomic, resilient to latency, and deterministically recoverable.

**Independent Test**: Inject 500ms network delay across all API calls, perform rapid folder creation, file renaming, link minting, and batch selection. Verify that loading indicators show consistently, duplicate clicks are discarded, and authoritative server state is reflected upon completion.

**Acceptance Scenarios**:

1. **Given** a user creating a new folder, **When** the creation API is in flight, **Then** the submit action is disabled to prevent duplicate folder creation, and upon success the new folder appears immediately in the file tree.
2. **Given** file deletion or link revocation, **When** confirmed, **Then** the UI provides clear undo or progress states, and the corresponding item or link row is authoritatively removed.
3. **Given** background session expiration while browsing, **When** any user action is triggered, **Then** the client seamlessly re-authenticates via stored credentials or gracefully redirects to login without corrupting the active view.

---

### Edge Cases

- **Moving Deep Empty Folders**: Moving an empty folder into another empty folder must preserve the virtual directory marker and update breadcrumb hierarchies accurately.
- **Move Collisions**: Moving a file `report.pdf` into a folder that already contains `report.pdf` must prompt the user with clear options (Keep Both / Overwrite / Cancel) rather than failing silently or corrupting metadata.
- **Large Directory Traversal**: When browsing destinations in a repository with hundreds of folders, the destination browser must include a quick folder filter/search input to locate target directories instantly.
- **Network Disconnect Mid-Move**: If the network connection drops during a batch move of 20 files, the UI must report exactly how many succeeded before the failure, restore interactive controls, and leave the view in a consistent, non-stuck state.

---

## Requirements *(mandatory)*

### Functional Requirements

#### Interactive Move Destination Browser (Area 1)
- **FR-001**: The move modal MUST feature a visual folder hierarchy browser displaying navigable child directories for the currently inspected level.
- **FR-002**: The move browser MUST include a breadcrumb navigation trail allowing users to jump back up to any ancestor folder or Root (`/`) with a single click.
- **FR-003**: The move browser MUST clearly display the currently selected target destination path (e.g. `Target: /documents/reports/`).
- **FR-004**: The move browser MUST disable selection of the current folder or any descendant directory of the item being moved, preventing circular moves visually before execution.
- **FR-005**: The move browser MUST include a real-time folder search/filter box to rapidly find nested folders in deep directory trees.
- **FR-006**: The move modal MUST offer an optional expandable "Manual Path" input for power users, but default to visual browsing.
- **FR-007**: Moving multiple files or folders MUST display the count and list of selected items in a compact collapsible header within the dialog.

#### Professional Design System & UI Overhaul (Area 2)
- **FR-008**: The application toolbar MUST be reorganized into standardized, visually distinct control groups (Ingest/Upload, View/Sort, Batch Actions, Admin Utilities).
- **FR-009**: All interactive buttons, dropdowns, and text inputs MUST adhere to consistent typography, height (standard 36px / compact 30px), padding, border radii, and hover/focus tokens.
- **FR-010**: The mobile layout MUST eliminate cramped multi-line button fragmentation through responsive flex-wrapping, collapsing text labels to tooltips/icons on narrow screens (<480px).
- **FR-011**: Empty states across file list, search results, trash, and link managers MUST display clear, contextual messaging with actionable shortcut buttons (e.g. "Upload File", "Clear Search").
- **FR-012**: Modal dialogs MUST share unified backdrop styling, header hierarchies, standardized close buttons (`Escape` key support), and explicit primary/secondary button orders.
- **FR-013**: Action confirmation dialogs for destructive operations (delete file, purge trash, revoke all links) MUST visually differentiate destructive danger buttons (red) from neutral actions.

#### Reliability, Async States & Recovery (Area 3 & 4)
- **FR-014**: All asynchronous mutating operations (folder create, rename, move, delete, link mint, cache purge) MUST disable triggering buttons and show inline progress to prevent duplicate clicks.
- **FR-015**: Any API failure across any user journey MUST display an actionable error message explaining the failure reason without leaving the UI permanently locked or spinners spinning infinitely.
- **FR-016**: Navigation between virtual folders via breadcrumbs, browser back/forward buttons, or folder clicks MUST maintain deterministic URL hash state (`#folder=...`) without losing view mode or sort preferences.
- **FR-017**: Media playback modal MUST cleanly release video resources and event listeners upon closing, preventing background audio/video playback or memory leaks.

---

### Key Entities

- **FolderNode**: Hierarchical representation of a virtual directory in the move browser. Attributes: `name` (string), `fullPath` (string), `isCurrent` (boolean), `isDescendantOfSource` (boolean), `childFolders` (FolderNode[]).
- **MoveContext**: Encapsulates the active relocation flow. Attributes: `selectedIds` (string[]), `currentBrowsingPath` (string), `selectedDestination` (string), `isValid` (boolean), `status` ("idle" | "browsing" | "moving" | "success" | "error").
- **DesignTokens**: Standardized styling variables on `:root` including spacing units (`--sp-xs`, `--sp-sm`, `--sp-md`, `--sp-lg`), button heights, and semantic action colors.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can navigate to and select a folder nested 5 levels deep in the move modal in under 5 clicks without typing any path characters.
- **SC-002**: 100% of illegal move operations (moving into self or descendant subfolders) are visually disabled in the move browser prior to user confirmation.
- **SC-003**: On mobile viewports (375px width), 100% of toolbar controls, modal dialogs, and cards fit within the screen without horizontal scrolling or overlapping controls.
- **SC-004**: During all async operations (move, delete, rename, folder creation), 100% of buttons display loading states and reject secondary duplicate clicks.
- **SC-005**: 100% of primary user journeys (login, browse, search, select, move, preview, settings) pass Playwright automated browser tests on desktop and mobile viewports.
- **SC-006**: 0% of transient network interruptions leave the application in an unrecoverable or permanently stuck loading state.

---

## Assumptions

1. **Virtual Folder Architecture**: Virtual directories in Anbar are derived from forward slashes in object `filename` attributes and dedicated 0-byte directory markers ending in `/`. The move destination browser aggregates these paths into a tree structure client-side from loaded objects.
2. **Responsive Breakpoints**: Standard breakpoints are Desktop (≥1024px), Tablet (768px–1023px), and Mobile (<768px). Touch targets on mobile must be at least 40px height.
3. **No External Framework Dependencies**: The design system and folder browser are implemented using clean, semantic vanilla HTML5, modern CSS custom properties, and standard DOM APIs within `src/anbar/ui/index.html` to preserve zero-dependency lightweight delivery.
