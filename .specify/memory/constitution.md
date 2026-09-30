<!--
Sync Impact Report:
- Version change: unversioned template -> 1.0.0 (initial ratification)
- Added principles:
  1. Correctness Over Superficial Patching
  2. Root-Cause Fixes Over Symptom Suppression
  3. User-Facing Behavior Verified Through Tests
  4. End-to-End Testing for Critical User Flows
  5. Reliable Browser Capability Detection
  6. Race-Safe Asynchronous and Server State
  7. First-Class Restart and Recovery Verification
  8. Deterministic Authentication and Session Lifecycle
  9. Persistent Working Records for Multi-Session Continuity
  10. Atomic Documentation as Part of Implementation
  11. Reproducible Production Deployment
  12. Strict Protection of Production Data and Secrets
  13. Isolation of Local Deployment Tooling
  14. Rigorous Acceptance Criteria Verification
  15. Deep Investigation of Regressions
- Added sections:
  - Mandatory Documentation and Synchronization Rules
  - Development Workflow, Dev/Prod Separation & Quality Gates
- Governance:
  - Amendment procedure, SemVer versioning policy, and audit compliance
- Follow-up TODOs: None.
-->

# Anbar Engineering Constitution

## Core Principles

### I. Correctness Over Superficial Patching
Every implementation MUST address design and semantic correctness rather than applying superficial patches, magic numbers, or string-based workarounds. Code MUST adhere to sound software engineering invariants, strict typing, and system data contracts. Developers MUST NOT apply cosmetic masks to conceal underlying behavioral flaws.

### II. Root-Cause Fixes Over Symptom Suppression
Defect resolution MUST identify and eliminate the fundamental root cause of an issue. Developers MUST trace every caller and consumer of an affected component before modifying it. Catching broad exceptions, swallowing errors, or adding defensive null-checks that hide deeper logical defects is strictly prohibited. The fix MUST be applied at the single source of truth where all flows converge.

### III. User-Facing Behavior Verified Through Tests
Every user-facing feature, API route, and behavioral change MUST be backed by automated test coverage before being considered acceptable. Unit and integration tests MUST assert real observable behaviors, contract boundaries, status codes, and payload integrity. Mocking MUST be confined to external network boundaries (such as Telegram API / MTProto network calls via `FakeBackend`); internal application logic MUST be exercised directly.

### IV. End-to-End Testing for Critical User Flows
Critical user workflows—including authentication, file ingestion, chunked streaming upload, resumable uploads, Range downloads, ZK encryption, video seeking, and dashboard management—MUST have automated end-to-end (E2E) verification. Browser-driven flows MUST be tested with real browser automation (Playwright) rather than simulated DOM stubs alone.

### V. Reliable Browser Capability Detection
Client-side media presentation, streaming playback, and format handling MUST rely on genuine browser capability detection and valid MIME types rather than naive file extension heuristics. Media players and preview containers MUST handle unsupported codecs, container formats, and Range responses gracefully with explicit user feedback and fallbacks.

### VI. Race-Safe Asynchronous and Server State
All asynchronous operations, shared memory caches, database accesses, and background workers MUST be provably race-safe. Concurrency MUST be governed through synchronization primitives (e.g., database locks, thread-safe stores, and explicit worker pools). UI components MUST maintain consistent state across concurrent requests, rapid user actions, network retries, and background job polling without orphan states or UI desynchronization.

### VII. First-Class Restart and Recovery Verification
Crash, restart, and recovery lifecycles MUST be treated as primary design requirements, not operational afterthoughts. Any persistent state (SQLite WAL, upload checkpoints, job queues, session files) MUST survive abrupt process termination without data corruption. Interrupted background jobs MUST be deterministically marked and recoverable upon restart, and tests MUST explicitly simulate restart sequences.

### VIII. Deterministic Authentication and Session Lifecycle
Authentication, cryptographic authorization, and session initialization MUST be fully deterministic across all interfaces (Web UI, Telegram Mini-App, API tokens, signed download URLs, and S3 gateway). Session bootstrap MUST eliminate race conditions on initial page load. Secrets and credentials MUST be masked in administrative views, and token validation MUST utilize constant-time comparison to prevent timing attacks.

### IX. Persistent Working Records for Multi-Session Continuity
Because engineering work spans multiple independent, stateless AI and human sessions, persistent working records are mandatory. Every engineering session MUST treat repository documentation as active working memory. At the conclusion of every implementation or verification turn, `docs/WORKING_RECORD.md` MUST be updated with current objectives, changes, test outcomes, and unambiguous next steps.

### X. Atomic Documentation as Part of Implementation
Documentation is not post-release technical debt—it is an atomic component of the implementation itself. Any change that alters an API contract, system architecture, runtime configuration, deployment invariant, or known bug list MUST update the corresponding documentation files (`API.md`, `ARCHITECTURE.md`, `DEPLOY.md`, `CHANGELOG.md`, `BUGS_AND_FIXES.md`) within the same pull request or commit.

### XI. Reproducible Production Deployment
Production deployments MUST be completely deterministic and reproducible. The application MUST run containerized with pinned dependency locks (`uv.lock`), clean base images, and immutable build artifacts. Docker configurations MUST enforce correct volume bindings, non-root execution where appropriate, and strict network isolation (loopback binding behind a TLS-terminating reverse proxy).

### XII. Strict Protection of Production Data and Secrets
Production SQLite databases, encryption keys, Telegram bot tokens, MTProto user session files (`.session`), and environment files MUST be rigorously guarded against exposure or data loss. Secrets MUST never be committed to Git or emitted in application logs, audit traces, or client-side bundles. Production data directories (`/opt/anbar/data`) MUST be accessed exclusively via absolute volume mounts.

### XIII. Isolation of Local Deployment Tooling
Local deployment automation scripts, operational shortcuts, and server management helpers MAY be developed on the local machine for developer efficiency, but they MUST remain strictly outside the Git repository or within ignored local paths. They MUST NEVER be committed to Git to prevent credential leaks, machine-specific path assumptions, or disruption of standard deployment procedures.

### XIV. Rigorous Acceptance Criteria Verification
No task, story, or bug fix is "done" merely because code was written, compiled, or refactored. Completion REQUIRES empirical verification: automated tests passing, acceptance criteria verified against running systems, and regressions ruled out. "Done" means verified, documented, and ready for production deployment.

### XV. Deep Investigation of Regressions
When an existing test fails or a regression occurs during development, developers MUST investigate the root failure mechanism rather than modifying test assertions, skipping test cases, or introducing brittle conditionals to force a green test suite. Every regression is a critical signal that an invariant has been violated.

---

## Mandatory Documentation and Synchronization Rules

Whenever code changes or verifications occur, specific project records MUST be updated in the same changeset:

| Stage | Document | Required Updates |
|---|---|---|
| **After Implementation** | `docs/WORKING_RECORD.md` | Log current objective, completed work, modified files, known issues, and next steps. |
| **After Implementation** | `CHANGELOG.md` | Add an entry under the current unreleased/active version categorized per Keep a Changelog (`Added`, `Fixed`, `Security`, `Reliability`, `Performance`). |
| **After Implementation** | `docs/API.md` | Update if any REST route, parameter, header, error code, or JSON payload is added, modified, or deprecated. |
| **After Implementation** | `docs/ARCHITECTURE.md` | Update if storage abstractions, concurrency models, data flows, or component boundaries change. |
| **After Implementation** | `BUGS_AND_FIXES.md` | Update when a tracked bug is addressed; document the root cause, fix, and prevention rule. |
| **After Implementation** | `docs/DEPLOY.md` / `README.md` | Update if configuration variables (`.env`), deployment requirements, or primary user flows change. |
| **After Verification** | `docs/WORKING_RECORD.md` | Record exact test suites executed, test counts passed/failed, missing coverage, E2E browser results, and deployment readiness status. |
| **After Verification** | `AUDIT_COVERAGE.md` | Update file status flags (`[~]`, `[x]`, `[!]`) and log findings for audited modules or security sweeps. |

---

## Development Workflow, Dev/Prod Separation & Quality Gates

### 1. Dev / Prod Environment Separation
- **Development**: Local development environment (`/home/hossein/Projects/Anbar`). All source code modifications, unit testing, mock testing, and browser E2E suites run locally.
- **Production**: Falkenstein remote server (`/root/anbar`, `/opt/anbar`, `https://dl.amiri-dev.ir/`). Code is deployed remotely only after local verification passes.
- **Production Mount Invariant**: The production container `anbar-anbar-1` mounts `/opt/anbar/data`, `/opt/anbar/secrets`, and `/opt/anbar/.env`. Production deployments MUST be executed from `/opt/anbar` using `docker compose -f compose.yaml up -d` to avoid relative volume path misdirection.

### 2. Quality Gates Before Release
1. **Static Analysis & Formatting**: Code MUST pass `ruff check` and `ruff format --check`.
2. **Type Checking**: API and core modules MUST pass `mypy` strict typing checks.
3. **Automated Unit & Integration Tests**: All pytest suites MUST pass cleanly without network calls (`FakeBackend` in CI/local).
4. **Browser E2E Tests**: Critical UI workflows MUST pass Playwright automated browser tests.
5. **Security & Secret Scan**: No secrets, private session files, or sensitive credentials in git diff.
6. **Documentation Sync**: All affected documentation files identified in the Documentation Rules table MUST be updated.

---

## Governance

1. **Constitutional Primacy**: This Constitution represents the supreme engineering policy for the Anbar repository. It supersedes informal team conventions, temporary development shortcuts, and unverified assumptions.
2. **Amendment Procedure**: Amendments to this Constitution require:
   - Explicit architectural rationale documented in an RFC or issue.
   - Impact assessment on existing features, tests, and deployment invariants.
   - Version increment according to the versioning policy below.
   - Simultaneous update of all dependent development instructions and working records.
3. **Versioning Policy**:
   - **MAJOR (X.0.0)**: Removal or fundamental redefinition of core principles or governance policies.
   - **MINOR (1.X.0)**: Addition of new principles, structural sections, or material expansion of existing rules.
   - **PATCH (1.0.X)**: Minor clarifications, phrasing improvements, typo fixes, or non-semantic adjustments.
4. **Compliance Review**: All proposed pull requests and code modifications MUST be audited against this Constitution. Any code introducing superficial patches, unverified assumptions, or undocumented API deviations MUST be rejected.

**Version**: 1.0.0 | **Ratified**: 2026-09-30 | **Last Amended**: 2026-09-30
