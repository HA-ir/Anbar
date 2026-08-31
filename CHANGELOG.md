# Changelog

All notable changes to **anbar** are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [SemVer](https://semver.org/).

## [0.15.15] — 2026-08-31

### Fixed
- **XSS in Telegram Mini App File List**: `renderList()` interpolated `f.filename` raw into `innerHTML` — a crafted filename executed HTML/JS inside the Telegram webview. Filenames (and ids in the copy handler) are now escaped, and the download link id is `encodeURIComponent`-ed. Found in audit loop #5.

## [0.15.14] — 2026-08-31

### Fixed
- **Stored XSS in Album Gallery Page (`/f/a/<token>`)**: Item filenames from the embedded JSON payload were interpolated into `innerHTML` without escaping — a filename like `<img src=x onerror=...>` executed on the public share page. Filenames (and the custom title) are now HTML-escaped server-side before the payload is embedded. Found in audit loop #4.

## [0.15.13] — 2026-08-31

### Fixed
- **S3 GetObject Range Parsing (500 → 416)**: Malformed (`bytes=abc-def`, `bytes=5-2`) or out-of-bounds (`bytes=150-`, oversized end) Range headers previously raised an unhandled `ValueError` and returned HTTP 500. Now parsed defensively: invalid ranges get a spec-compliant XML `InvalidRange` 416, oversized ends are clamped to the last byte (RFC 9110 §14.2), and multi-range requests fall back to serving the full object.
- **UI: Storage Legend Missing "Other"**: The storage-distribution legend omitted the `other` category even though the bar itself (`sdOth`) renders it — legend now lists it when non-zero.

## [0.15.12] — 2026-08-31

### Fixed
- **Content-Disposition Header Sanitization (RFC 5987)**: Unicode filenames (e.g. Persian) no longer crash the download endpoint with a 500 (`latin-1` encode error); the header now carries an ASCII fallback plus a percent-encoded `filename*` parameter, and CR/LF/quote characters can no longer break or inject headers.
- **`X-Content-Type-Options: nosniff`** on all `/f/{id}` download responses to eliminate MIME-sniffing XSS on user-uploaded files.
- **Telethon Client Leak in MTProto Auth**: `send-code` / `verify-code` now always disconnect the temporary Telegram client (`finally`), including the `need_password` and invalid-code paths — failed attempts no longer keep live MTProto sockets open.
- **Typed MTProto Auth Errors**: Specific Persian error messages for invalid/expired OTP code, invalid phone number, wrong 2FA password, and FloodWait (HTTP 429) instead of raw exception dumps.
- **UI: Double-Init Guard**: `initTgAuthUI()` no longer re-binds `onclick` handlers every time the settings drawer opens (single init).
- **UI: Stale `session_set` Check**: Telegram auth status box now keys only on the server-provided `session_authorized` field (the `r.session_set` field never existed on the API).

### Changed
- UI: minor cleanup — duplicate semicolon after `newFolderBtn` guard wrapper; consistent `$()` selector in the folder-creation guard.

## [0.15.11] — 2026-08-31

### Added
- **Telegram MTProto Interactive Auth (UI + API)**: In-browser OTP login flow (`/admin/telegram/send-code`, `/admin/telegram/verify-code`, `/admin/telegram/logout`) with 2FA password support, persisting the authorized session to `cfg_tg_session` — no more manual `anbarctl login`.
- **Path-Encoded Delete/Rename**: `DELETE` and `PATCH /f/{obj_id:path}` now accept object ids containing slashes (folder-scoped ids).
- **UI: Double-Submit Guards**: `guardBtn()` wrapper on destructive/async buttons (logout, delete, bulk ZIP, secret rotate/set, new folder) preventing double clicks.
- **UI: Select-All Reflection**: the select-all button now highlights (`.view-on`) and toggles its label (همه/هیچ) when every visible file is selected.
- **UI: Channel Rebuild Feedback**: progress toast, restored button state, and automatic list refresh + breadcrumb reset after a channel rebuild.
- **UI: Telegram Auth Boxes**: connected (green) vs. login-form states driven by the Telegram config endpoint.

## [0.15.7] — 2026-08-29

### Fixed
- **Toast Single-Line Formatting & Localization**: Fixed multi-line break issue on Client-Side ZK toggle notification by enforcing `white-space: nowrap` on `.toast` and properly localizing the toggle status messages with leading icons.

## [0.15.6] — 2026-08-29

### Added
- **Client-Side True Zero-Knowledge Encryption (WebCrypto API)**: In-browser optional client-side encryption (`ANBAR_ZK1` binary format with PBKDF2-HMAC-SHA256 and AES-256-GCM) protecting files before they ever leave the client's device, with transparent on-the-fly decryption during downloads.
- **CLI Client ZK Tooling**: Added `anbarctl encrypt` and `anbarctl decrypt` commands for offline local encryption and decryption with custom passwords.

## [0.15.5] — 2026-08-29

### Fixed
- **LRU Invalidation on Folder Renames**: Invalidate in-memory `_ObjectLRU` cache during `Database.rename_folder` to ensure instant consistency of updated object paths.

## [0.15.4] — 2026-08-29

### Added
- **Conditional & Batched Delete Tombstones (`del_batch`)**: Only emit delete tombstones if remote chunk deletion fails on Telegram (zero chat pollution when deletion succeeds), with batched event payloads to prevent FloodWait rate-limiting.

## [0.15.3] — 2026-08-29

### Added
- **Channel Meta Event Journaling (Tombstones & Replay)**: Automated encryption and emission of metadata lifecycle events (`anbar:v1:evt:e:...` / `anbar:v1:evt:p:...`) on folder rename, object rename, object move, and hard purge, allowing exact directory hierarchy replay during zero-database disaster recovery.

## [0.15.2] — 2026-08-29

### Added
- **Self-Describing & Self-Healing Encrypted Storage (Disaster Recovery)**: Embedded compact, zero-knowledge encrypted metadata envelopes into Telegram document chunk captions (`anbar:v1:e:...` / `anbar:v1:p:...`).
- **Channel History Rebuild Engine**: Automated channel crawler (`POST /api/v1/admin/channel/rebuild` & UI button) that walks Telegram channel messages, decrypts metadata envelopes using the user's master secret, sorts chunks and fully reconstructs the SQLite database, files, paths and manifests from scratch without local database backups.

## [0.15.1] — 2026-08-29

### Added
- **In-Memory Hot Metadata LRU Cache**: Zero-I/O in-memory LRU cache (`_ObjectLRU`, capacity 4,000) for hot object metadata and manifests in `Database`, slashing TTFB to sub-millisecond speeds.
- **Adaptive Deep Lookahead Prefetching**: Dual-buffer lookahead pipeline in streaming download, prefetching upcoming segments concurrently to eliminate streaming latency.
- **Master Secret Custom Setting & Dynamic Rotation**: Dedicated admin UI and API (`GET/POST /api/v1/admin/auth/secret`, `/api/v1/admin/auth/rotate-secret`) for configuring custom master HMAC/encryption secrets or triggering cryptographically secure rotations.
- **Daily Auto-Backup Master Switch**: Runtime tunable toggle (`auto_backup_enabled`) with UI switch in the admin drawer.
- **Top-Most Toast Stacking**: Re-elevated `#toasts` container with `z-index: 99999` and non-blocking pointer events.

## [0.15.0] — 2026-08-29

### Added
- **Predictive Chunk Prefetching**: Pipelined bounded lookahead prefetching during streaming download; while chunk $N$ is being served to the client, chunk $N+1$ downloads concurrently in the background, eliminating buffering stalls.
- **Directory Tree Drag & Drop Upload**: Recursive batch traversal for dropped folder hierarchies (`webkitGetAsEntry`) and dedicated folder upload button (`#upFolderBtn`).
- **Rich Markdown Document Preview**: Built-in renderer with interactive tabs (Rendered View vs. Raw Code), markdown tables, task checkboxes, code syntax blocks, blockquotes, and links.
- **Storage Breakdown Telemetry & Distribution Bar**: Real-time category breakdown (Images, Videos, Audio, PDF, Text/Code, Archives, Others) with colored progress visualization in the admin drawer.
- **Security Audit Logging System** (`GET /api/v1/admin/audit-logs`): SQLite-backed audit log tracking sensitive admin actions and automated events with an interactive drawer viewer.
- **Automated Daily Backup Daemon**: Automated periodic database snapshotting and push to Telegram storage.
- **Telegram Mini App Enhancements**: Responsive `/tg-app` with native theme synchronization (`themeParams`), file search, and haptic feedback.

## [0.14.3] — 2026-08-29

### Added
- **Revoke All Active Links** (`POST /api/v1/admin/links/revoke-all`): Added backend endpoint and UI button in Active Links modal to immediately revoke all existing share links.
- **Zero-Knowledge Telegram Opaque Chunks**: All chunks stored on Telegram channels use randomized opaque filenames (`blob_<hex>_<idx>.bin`) and generic binary MIME types, eliminating metadata leakage in the storage channel.
- **Zero-Overhead File & Folder Duplication** (`POST /api/v1/admin/objects/copy` & `POST /api/v1/admin/folders/copy`): Create instant duplicate files/directories by duplicating SQLite manifest metadata pointing to existing chunks with zero storage/bandwidth overhead.
- **Disaster Recovery & Database Backup/Restore**:
  - `GET /api/v1/admin/backup`: Download consistent SQLite database snapshot.
  - `POST /api/v1/admin/backup/telegram`: Push backup directly to the configured Telegram channel.
  - `POST /api/v1/admin/backup/import`: Atomic validation and restore of SQLite backup snapshots.
- **System Telemetry & Health Dashboard** (`GET /api/v1/admin/system-stats`): Real-time metrics for total objects, total bytes, total downloads, active bot counts, encryption status, and last backup timestamp.
- **Bounded Code & Text Preview with Highlighting**: Syntax highlighting and line numbers for code/text files capped at 100 lines with an "Open full in new tab" action to prevent browser DOM freezing.
- **Persian (Shamsi) Date BiDi Formatting**: Strict Shamsi date and time formatting with BiDi isolation (`۷ شهریور ساعت ۰۰:۱۸`).

## [0.11.0] — 2026-08-24

### Added
- **OVH-streamed big-file benchmark** (`scripts/bench_ovh.py`): streams test
  payloads live from `proof.ovh.net` through the server to Telegram — zero
  local disk, constant ~15 MB client RSS via a FIFO + chunked-TE pump, exact
  byte accounting with per-segment resume when the source edge drops.
- **10 GB upload verified end-to-end** on the `bot` backend: 640 × 16 MB
  chunks, ~32.5 min (5.2 MB/s sustained) with flood pacing absorbing every
  rate-limit window. README benchmark table now covers 500 MB / 1 GB /
  10 GB rows with total wall time per size.
- **Security scanning in CI**:
  - weekly `pip-audit` job over runtime dependencies (fails on known CVEs);
  - Trivy HIGH/CRITICAL gate on the published GHCR image after each push.
- Documented the **resumable upload** flow (`X-Upload-Id` /
  `X-Resume-From`) in `docs/API.md`, including a verified drop-and-resume
  scenario on a 100 MB payload (send-side SHA-256 == server SHA-256).

### Changed
- Runtime setting ceiling for `max_upload_mb` raised from 2 048 to
  102 400 MB so multi-GB objects can be allowed deliberately; nginx
  `client_max_body_size` guidance updated accordingly.
- Benchmark methodology: payloads are streamed from an external source
  instead of generated locally, so measured times reflect pure
  server + Telegram transfer.

## [0.10.8] — 2026-08-23

- Bugfix release: hardening around body idle timeouts and flood-budget
  handling; benchmark harness rewritten for streaming (low-RSS) operation;
  OSS packaging pass (SECURITY.md, CONTRIBUTING.md, CI, GHCR publishing).
