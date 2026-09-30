# Phase 1 Data Model: Anbar Stabilization and UX Reliability

## Entities & State Structures

### 1. FileObject Entity
Represents a stored file or folder marker in the frontend state.
- `id`: `string` — Unique identifier (e.g. `FuYGddJNWTGh` or `folder:documents/sub/`).
- `filename`: `string` — Virtual path (e.g. `documents/2026/report.pdf` or `archive/`).
- `size`: `number` — Size in bytes (0 for directory markers).
- `content_type`: `string` — MIME type (e.g. `video/x-matroska`, `image/jpeg`).
- `created_at`: `number` — Unix epoch timestamp.
- `hasThumb`: `boolean` — Whether a pre-generated 256px thumbnail exists.
- `downloaded`: `number` — Lifetime download counter.
- `isFolder`: `boolean` — Derived flag (true if virtual directory).
- `itemCount`: `number` — (For folders) Number of child objects aggregated.

### 2. SelectionState Entity
Represents user selection state in `src/anbar/ui/index.html`.
- `selSet`: `Set<string>` — Active set of selected object IDs / folder IDs.
- `selectMode`: `boolean` — Flag indicating whether multi-select mode is active.
- `cachedVisibleCount`: `number` — Count of selectable items currently rendered in view.
- **State Transitions**:
  - `IDLE` (selectMode=false, selSet=empty)
  - `ACTIVE` (selectMode=true, selSet size > 0)
  - `SELECT_ALL` (selectMode=true, selSet contains all visible items)
  - `DESELECT_ALL` (selectMode=true, selSet emptied)

### 3. MoveOperation Entity
Represents an in-flight file relocation operation.
- `sourceIds`: `string[]` — Array of file or folder IDs to move.
- `destination`: `string` — Normalized destination folder prefix (e.g. `""` for root, or `media/video`).
- `status`: `"idle" | "validating" | "in_flight" | "completed" | "failed"` — Operational state.
- `progress`: `{ current: number, total: number, message: string }` — Progress status.
- `validationError`: `string | null` — Validation error message (e.g. "Cannot move a folder into itself").
- `results`: `{ moved: number, skipped: string[], errors: string[] }` — Post-execution summary.

### 4. MediaPlaybackState Entity
Represents client media playback readiness and error diagnosis.
- `objectId`: `string` — Media object identifier.
- `url`: `string` — Media stream URL (`/f/{id}`).
- `filename`: `string` — Stored filename.
- `isMkv`: `boolean` — Derived from extension or `video/x-matroska`.
- `status`: `"unloaded" | "metadata_loading" | "playing" | "error"` — Video element state.
- `errorCode`: `number | null` — `HTMLMediaElement.error.code`:
  - 1: `MEDIA_ERR_ABORTED`
  - 2: `MEDIA_ERR_NETWORK`
  - 3: `MEDIA_ERR_DECODE` (codec unsupported or corrupted stream)
  - 4: `MEDIA_ERR_SRC_NOT_SUPPORTED` (format/container unsupported)
- `fallbackReason`: `"codec_unsupported" | "network_error" | null` — Categorized failure reason.

### 5. SearchState Entity
Represents the search filter synchronization state.
- `inputValue`: `string` — Raw text in `#fSearch` DOM element.
- `fQuery`: `string` — Normalized active search query in JavaScript memory.
- `debounceTimer`: `number | null` — Active `setTimeout` identifier (75ms).
- `cacheKey`: `string` — Compound key for folder/view caching.

### 6. SessionAuthState Entity
Represents client-side authentication readiness.
- `apiKey`: `string` — Raw API key stored in `localStorage` (admin).
- `cookieValid`: `boolean` — Whether HTTP-only `anbar_session` cookie is currently active.
- `reLoginPromise`: `Promise<boolean> | null` — Singleton in-flight re-login request to avoid concurrent race conditions.
- `authenticated`: `boolean` — Overall auth flag (`authed` in UI).
