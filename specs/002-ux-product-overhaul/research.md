# Phase 0 Research: Anbar Product Quality & UX Overhaul

## Technical Decisions & Architecture Choices

### 1. Visual Hierarchical Move Browser Architecture
- **Decision**: Implement a client-side virtual directory navigator inside `#moveModal`. Maintain an active cursor state `moveBrowsePrefix` (e.g. `""` for root, or `"media/videos/"`). Render clickable directory items representing direct child folders of `moveBrowsePrefix`, along with a clickable breadcrumb navigation trail (`Root / media / videos`).
- **Rationale**: Currently, `#moveChips` extracts prefixes from loaded objects and dumps them as a flat horizontal list. If a directory is 4 levels deep (`a/b/c/d/`), the user is forced to manually type `/c/d/`. With an active browsing cursor, users can visually click into child folders, jump back via breadcrumbs, and confirm relocation without ever typing.
- **Alternatives Considered**:
  - *Full recursive tree view (accordion-style)*: Can cause vertical scrolling bloat on mobile viewports (<375px) when hundreds of folders exist. Drill-down browser with breadcrumbs provides cleaner focus, zero clutter, and native mobile touch ergonomics.

### 2. Semantic Toolbar Grouping & Design Tokens
- **Decision**: Partition the flat toolbar into three semantic flex clusters:
  1. `.toolbar-group-primary`: Upload button & URL Ingest toggle.
  2. `.toolbar-group-view`: Type Filter select, Sort select, Gallery/Table toggle.
  3. `.toolbar-group-actions`: Select Mode toggle, Trash button, Links Manager, Settings.
  Standardize all button heights to 36px (desktop) / 32px (compact/mobile), unified 10px border radius, and tokenized spacing (`--sp-xs: 4px`, `--sp-sm: 8px`, `--sp-md: 12px`, `--sp-lg: 16px`).
- **Rationale**: Live screenshots revealed that 11 un-grouped controls cause chaotic 4-row fragmentation on mobile. Clustered flex items wrap predictably and collapse cleanly.
- **Alternatives Considered**:
  - *Hamburger menu for all actions*: Hiding essential actions (like Select or View Toggle) adds unnecessary click friction. Grouped flex layout keeps primary actions visible while maintaining clean visual balance.

### 3. Universal Async Guarding & Progress States
- **Decision**: Implement the `guardBtn` / loading spinner pattern across all mutating modal actions:
  - `#newFolderBtn` / Folder Creation
  - `#renameObj` / File Renaming
  - `#moveOk` / Move Execution
  - `#shareOptsOk` / Link Minting
  - `#trashPurgeBtn` / Trash Purge
- **Rationale**: High-latency environments or repeated clicks can fire multiple concurrent requests before the first completes, risking race conditions and duplicate operations. Disabling buttons and rendering an active spinner guarantees atomic operations.
- **Alternatives Considered**:
  - *Global full-screen loader*: Interrupts background browsing and feels clunky. In-place button spinners maintain context without blocking the whole page.

### 4. Purposeful Contextual Empty States
- **Decision**: Enhance `#empty` (empty directory) and `#noMatch` (zero search results) with distinct SVG icons, friendly descriptive titles, and contextual action buttons ("Upload Files" in empty folders; "Clear Search" in zero search results).
- **Rationale**: Plain text "هنوز فایلی آپلود نکرده‌ای" looks like un-styled debug output. Visual empty states reassure users and provide immediate recovery shortcuts.
