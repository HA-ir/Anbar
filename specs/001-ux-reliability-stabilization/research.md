# Phase 0 Research: Anbar Stabilization and UX Reliability

## Technical Decisions & Architecture Choices

### 1. Selection Architecture (Freezing Elimination)
- **Decision**: Decouple selection state mutations from list rendering. Selection toggles MUST mutate `.selected` classes and checkbox `.checked` properties in-place via DOM queries and event delegation, rather than calling `renderRows()` or `renderGallery()`.
- **Rationale**: In `src/anbar/ui/index.html`, `renderRows()` and `renderGallery()` destroy all existing DOM nodes (up to 500 rows or cards with video/img elements and listeners) and rebuild them synchronously. In-place DOM updates complete in <5ms for 500 elements versus >300ms + memory garbage collection for full rebuilds.
- **Alternatives Considered**:
  - *Virtual DOM / Virtual scrolling*: Rejected because Anbar uses vanilla JavaScript in `index.html`; introducing a heavy framework violates Constitution Principle I & Ponytail mode. In-place DOM mutation solves the freeze with zero new dependencies.

### 2. File Move UX Architecture
- **Decision**: Convert `openMoveModal()` into an active state machine: `idle` → `validating` → `in_flight` (spinner + disabled buttons) → `completed` (summary reporting). Perform client-side path validation preventing moves to current path or into subfolders of the source folder.
- **Rationale**: Currently `doMove()` closes the modal before starting network requests and silently treats invalid circular folder moves as `ok++`. Keeping the modal open with progress indicators ensures transparency, prevents duplicate clicks, and informs users of skipped/failed items.
- **Alternatives Considered**:
  - *Background notification toast only*: Rejected because users lack progress visibility on batch moves (e.g. 50 files) and cannot know if an operation is still in-flight.

### 3. Media Capability & MKV Playback Architecture
- **Decision**: Provide `<video>` with explicit `<source>` tags specifying `video/x-matroska`, test playback capability, and inspect `video.error.code` (`MEDIA_ERR_DECODE`, `MEDIA_ERR_SRC_NOT_SUPPORTED`, `MEDIA_ERR_NETWORK`) before falling back.
- **Rationale**: Chromium and modern browsers support MKV demuxing with H.264/AAC/VP9/AV1. The current code assumes `.mkv` extension equals unplayable on any error, falsely blocking native playback.
- **Alternatives Considered**:
  - *Client-side WebAssembly demuxer (ffmpeg.wasm)*: Rejected due to 30MB+ payload size, memory overhead, and CPU load. Native browser capability with proper error distinction is cleaner and zero-overhead.

### 4. Search State Synchronization Architecture
- **Decision**: Invalidate `searchDebounceTimer` synchronously inside `#fClear.onclick` and backspace clears. Invalidate `folderViewCache` search keys when search is cleared, and ensure `fQuery` and `#fSearch.value` remain atomically in sync.
- **Rationale**: `#fClear.onclick` currently clears the input and calls `renderRows()`, but leaves `searchDebounceTimer` active if typed within 75ms. When the timer fires, or when `folderViewCache` restores stale cached DOM nodes, the old search query resurfaces.
- **Alternatives Considered**:
  - *Server-side search API*: Current dataset (<500 objects) is cached locally in SQLite/memory; client-side filtering is instantaneous when timer leaks and cache collisions are resolved.

### 5. Startup & Cold-Restart Lifecycle
- **Decision**: Update `api()` to transparently await re-login and retry a 401-failed request once before throwing. Serialize session verification in `boot()` / `showApp()` before dispatching parallel `/admin/status` and `/admin/objects` queries.
- **Rationale**: Concurrent 401s on cold start cause race conditions in `api()`, setting `files = []` and leaving the file view blank until sequential calls in Settings later mint the session cookie.
- **Alternatives Considered**:
  - *Hard page reload on 401*: Rejected because it causes infinite reload loops if credentials are stale. Transparent single retry after `/ui/login` is robust and standard.

### 6. Falkenstein Production Deployment Architecture
- **Decision**: Standardize remote deployment to run exclusively from `/opt/anbar` via `docker compose -f compose.yaml up -d`, preserving absolute mounts (`/opt/anbar/data`, `/opt/anbar/secrets`, `/opt/anbar/.env`). Create a local helper script outside Git (e.g., `~/Projects/Anbar/.local_deploy.sh` or local untracked) to automate SSH, git pull, build, compose, and healthz checks.
- **Rationale**: Conforms to BUG-37 prevention and Constitution Principles XI, XII, and XIII.
