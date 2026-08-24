# Changelog

All notable changes to **anbar** are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [SemVer](https://semver.org/).

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
