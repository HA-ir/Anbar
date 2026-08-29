# Changelog

All notable changes to **anbar** are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [SemVer](https://semver.org/).

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
