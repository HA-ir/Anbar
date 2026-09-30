# Phase 1 Data Model: Anbar Product Quality & UX Overhaul

## Entities & State Structures

### 1. MoveBrowserState Entity
Encapsulates client-side navigation within the Move dialog.
- `sourceIds`: `string[]` — IDs of items being moved.
- `sourcePrefix`: `string` — Directory path currently housing the items (e.g. `""` for root or `"media/"`).
- `currentBrowsePrefix`: `string` — Folder currently open inside the move picker (e.g. `"media/videos/"`).
- `breadcrumbs`: `{ label: string, path: string }[]` — Navigable ancestor segments.
- `childFolders`: `{ name: string, fullPath: string, isIllegal: boolean }[]` — Direct subfolders of `currentBrowsePrefix`.
- `filterQuery`: `string` — Search text to filter displayed child folders.
- `manualMode`: `boolean` — Whether the advanced manual text input is expanded.
- `status`: `"idle" | "in_flight" | "success" | "error"` — Operational state.

### 2. DesignTokens Entity
CSS custom properties defining unified layout dimensions on `:root`.
- `--btn-h`: `36px` (desktop), `32px` (mobile).
- `--btn-radius`: `10px`.
- `--sp-xs`: `4px`, `--sp-sm`: `8px`, `--sp-md`: `12px`, `--sp-lg`: `16px`.
- `--tx`: Primary text color; `--tx2`: Secondary text; `--tx3`: Hint/tertiary text.
- `--bg`: Background plate; `--bg2`: Elevated card/modal surface; `--bg3`: Input/badge fill.
- `--line`: Subtle border; `--line2`: Control border; `--line-focus`: Active control focus ring.

### 3. ToolbarState Entity
State managing grouped toolbar rendering and responsiveness.
- `viewMode`: `"gallery" | "table"`.
- `uploadOpen`: `boolean`.
- `selectMode`: `boolean`.
- `activeFilterType`: `"" | "image" | "video" | "audio" | "pdf" | "other"`.
- `sortMode`: `"new" | "old" | "big" | "small" | "dl" | "name"`.
- `isMobile`: `boolean` (derived via `window.matchMedia("(max-width: 480px)")`).

### 4. AsyncActionGuard Entity
State tracking in-flight asynchronous operations to prevent duplicate execution.
- `actionId`: `string` — Identifier of the active action (e.g. `move`, `rename`, `create_folder`).
- `inFlight`: `boolean` — Whether the operation is actively executing.
- `cancelRequested`: `boolean` — Whether user requested cancellation.
