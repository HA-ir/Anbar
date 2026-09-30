# Anbar — Multi-Session Working Record

> **Standard:** Adheres to the 20 foundational engineering rules established for the Anbar multi-session task.
> **Last Updated:** 2026-09-30 (Tehran / Local)
> **Branch:** `main`
> **Current Git Commit:** `6c8d62e` (docs: ratify engineering constitution v1.0.0)

---

## 1. Operating Rules & Core Constraints

1. **Multi-session continuity**: Never assume a future session remembers anything from a previous session. Persist all critical state here and in repository documentation.
2. **Persistent working memory**: Existing documentation files are preserved as historical records and active specifications:
   - `README.md`
   - `BUGS_AND_FIXES.md`
   - `IMPROVEMENT_PLAN.md`
   - `AUDIT_COVERAGE.md`
   - `CHANGELOG.md`
   - `HYBRID_PLAN.md`
   - `docs/` (`API.md`, `ARCHITECTURE.md`, `DEPLOY.md`, `DISASTER_RECOVERY.md`, `ROADMAP.md`, `WORKING_RECORD.md`)
   - `tests/`
3. **Session boundary updates**: Every meaningful implementation/test session updates this record with:
   - Current objective
   - Completed work
   - Files/components changed
   - Tests executed
   - Tests still missing
   - Known failures
   - Deployment status
   - Current git commit/branch
   - Exact next step for the next session
4. **Verification before completion**: Code written is never marked complete without actual verification.
5. **Root cause over symptom**: Prefer fixing root causes over adding special cases.
6. **Feature preservation**: Do not remove existing functionality merely to make a test pass.
7. **Production & Data Preservation**:
   - Production server: `Falkenstein` (`/root/anbar`, `https://dl.amiri-dev.ir/`).
   - Production container: `anbar-anbar-1` mounted to absolute host paths:
     - `/opt/anbar/data` -> `/app/data` (persistent SQLite DB & object records)
     - `/opt/anbar/secrets` -> `/app/secrets` (MTProto sessions)
     - `/opt/anbar/.env` -> `/opt/anbar/.env` (credentials)
   - Production deploys MUST always run: `cd /opt/anbar && docker compose -f compose.yaml up -d` (never use `docker/compose.yaml` with relative mounts in production — ref: BUG-37 in `BUGS_AND_FIXES.md`).
8. **Dev/Deploy Separation**:
   - Development environment: Local laptop at `/home/hossein/Projects/Anbar`.
   - Deployment environment: Remote `Falkenstein` server.
   - Helper deployment scripts must remain local/untracked and never committed to Git.
   - No secrets, tokens, `.env` files, or deployment credentials committed to Git.
9. **Testing & Verification Standard**:
   - Automated and E2E coverage for user-facing features.
   - Browser testing in real browsers (e.g. Playwright) for browser-dependent functionality.
   - Explicit testing of race conditions, repeated actions, reloads, cold starts, and stale state for asynchronous behavior.
10. **Final Completion Gate**:
    - Implementation complete
    - Unit, integration, and E2E tests pass
    - Production deployment succeeds on Falkenstein
    - Production smoke tests pass
    - Documentation and working records updated
    - Clean git status (except intentional untracked local helper files)
    - Zero known reproducible failures in requested scope

### 1.1 Engineering Constitution (`.specify/memory/constitution.md`)
Ratified on 2026-09-30 (v1.0.0). Mandates:
- 15 core principles (Correctness over superficial patching, root-cause fixes, user-facing behavior verified by tests, E2E browser testing, browser capability detection over extension heuristics, race-safe async/server state, restart/recovery as first-class, deterministic auth/session lifecycle, persistent working records, atomic documentation during implementation, reproducible deployment, strict protection of secrets & production data, isolation of local deployment tooling, acceptance criteria verification, deep investigation of regressions).
- Documentation synchronization matrix:
  - Implementation: `docs/WORKING_RECORD.md`, `CHANGELOG.md`, `docs/API.md`, `docs/ARCHITECTURE.md`, `BUGS_AND_FIXES.md`, `docs/DEPLOY.md`/`README.md`.
  - Verification: `docs/WORKING_RECORD.md`, `AUDIT_COVERAGE.md`.

---

## 2. Environment Status

- **Development Laptop**: `/home/hossein/Projects/Anbar`
- **Remote Host**: `Falkenstein` (`/root/anbar`, `/opt/anbar`, `https://dl.amiri-dev.ir/`)
- **Codebase Memory Status**: Indexed (`home-hossein-Projects-Anbar`, 2,537 nodes, 10,057 edges, artifact at `.codebase-memory/graph.db.zst`)
- **Claude Capability Bridge**: Active (kernel loaded, capability cards routed)

---

## 3. Session Log

### Session 0: Initialization & Rule Adoption (2026-09-30)

- **Current Objective**: Establish persistent multi-session memory, adopt the 20 engineering rules, initialize codebase memory indexing, and document repository baseline.
- **Completed Work**:
  - Adopted and codified 20 multi-session rules into persistent memory (`/home/hossein/.claude/projects/-home-hossein-Projects-Anbar/memory/anbar-multi-session-rules.md`) and `docs/WORKING_RECORD.md`.
  - Loaded `claude-capability-bridge` kernel and protocol.
  - Indexed the repository with `codebase-memory-mcp` (2,537 nodes, 10,057 edges).
  - Inspected existing documentation files (`README.md`, `BUGS_AND_FIXES.md`, `IMPROVEMENT_PLAN.md`, `AUDIT_COVERAGE.md`, `CHANGELOG.md`, `HYBRID_PLAN.md`, `docs/`, `tests/`).
  - Identified critical production deployment invariants (BUG-37 prevention: `/opt/anbar` absolute mounts).
- **Files/Components Changed**:
  - `docs/WORKING_RECORD.md` (created)
  - `~/.claude/projects/-home-hossein-Projects-Anbar/memory/anbar-multi-session-rules.md` (created)
  - `~/.claude/projects/-home-hossein-Projects-Anbar/memory/MEMORY.md` (created)
  - `.codebase-memory/graph.db.zst` (generated by indexer)
- **Tests Executed**:
  - Indexing validation via `index_repository`.
- **Tests Still Missing**:
  - None for initialization.
- **Known Failures**:
  - None currently recorded in baseline.
- **Deployment Status**:
  - Production is at `https://dl.amiri-dev.ir/` (Falkenstein).
  - Local is at `a5e61ee` (v0.15.56).
- **Current Git Commit / Branch**:
  - `a5e61ee` on `main`.
- **Exact Next Step for Next Session**:
  - Ratify project constitution using Spec Kit.

### Session 1: Engineering Constitution Ratification (2026-09-30)

- **Current Objective**: Establish the official Anbar Engineering Constitution via `/speckit-constitution`, enshrining the 15 core engineering principles and the documentation synchronization matrix.
- **Completed Work**:
  - Inspected repository architecture, docs, test suites, and Docker deployment conventions.
  - Resolved `constitution-template` and drafted `.specify/memory/constitution.md` (v1.0.0).
  - Codified the 15 non-negotiable principles, documentation rules, quality gates, and governance policies.
  - Synchronized `docs/WORKING_RECORD.md` with the new constitution rules.
- **Files/Components Changed**:
  - `.specify/memory/constitution.md` (written/ratified v1.0.0)
  - `docs/WORKING_RECORD.md` (updated)
- **Tests Executed**:
  - Constitution consistency check, placeholder validation, and structure verification.
- **Tests Still Missing**:
  - N/A (governance update).
- **Known Failures**:
  - None.
- **Deployment Status**:
  - No application code changed. Deployment unchanged at v0.15.56.
- **Current Git Commit / Branch**:
  - `a5e61ee` on `main`.
- **Exact Next Step for Next Session**:
  - Proceed with the next Spec Kit workflow step (`/speckit-specify` or specific feature specification).
