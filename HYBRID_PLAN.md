# anbar Hybrid Download — Comprehensive Continuation Plan
**Session date:** 2026-08-26 · **Prepared for upload into a fresh session**

## Current state (all verified, do NOT re-do)

### Production
- `/opt/anbar` container running: `ANBAR_BACKEND=mtproto`, `ANBAR_CHUNK_SIZE_MB=49` (restored)
- Repo `/root/anbar` @ commit `4710c40` (README has definitive 10GB A/B table)
- Tests: 164 passed. Deployed image = latest (pipelined GetFile window + admin toggle)
- Admin toggle `mtproto_export_conns` exists (POST /admin/settings), default OFF, keep OFF
- Disk: `/` is 95% full (2.2G free) — the 10GB source lives in /root/ovh10g/ (12×854MB parts,
  sha256 b626371c7c9c245b…), DO NOT delete without asking Hossein

### Test objects still stored in Telegram (both full 10GB, sha-verified uploads)
- **FuYGddJNWTGh** — uploaded via **bot**, 16MB chunks (640 file_ids in anbar DB manifest)
- **kd2qu7aYzWfv** — uploaded via **mtproto**, 16MB chunks (~640 msgs in MT channel)
- Old 49MB-chunk 10GB object from earlier runs may also exist; ignore.

### Proven facts (live-tested, trust these)
1. Bot is a member of the MTProto channel and RECEIVES `channel_post` updates with
   `document.file_id` for every doc posted there (privacy mode allows it).
2. `getFile` works on those file_ids; 15MB chunk downloads at **66 MB/s** via bot CDN.
3. Bot API getFile hard cap = **20MB per file** → hybrid chunks must be ≤19MB (use 16MB).
4. Bot CDN **truncates large multi-chunk streams at ~1.4–2.8GB** — observed twice on
   FuYGddJNWTGh full-GET attempts (harness urllib + curl --retry). Root cause UNKNOWN:
   could be Telegram-side throttling of sequential getFile volume OR missing retry on a
   transient error inside our streaming generator.
5. Same-DC auth export is server-blocked (`DC_ID_INVALID`) → true multi-socket MTProto
   download impossible with one session. Don't retry that path.
6. 10GB A/B results @16MB chunks (2026-08-26): mt up 729s/14.04MB/s, dl 1965s/5.21MB/s
   sha OK · bot up 1985s/5.16MB/s (43 flood-waits), dl truncated → unusable alone.

### Goal
Hybrid single-store design: upload via mtproto (fast, message-based), bot harvests
file_ids from channel_post updates during upload, downloads served by bot getFile (CDN),
fallback to mtproto open() when bot_file_id missing. Chunks unified at 16MB.

---

## PHASE 0 — Session restore checklist (~2 min)
```bash
cd /root/anbar && git log --oneline -3        # expect 4710c40 on top
cd /opt/anbar && docker compose ps           # anbar-anbar-1 Up
curl -s http://127.0.0.1:8318/healthz        # {"status":"ok"}
grep -E 'ANBAR_BACKEND|ANBAR_CHUNK' .env     # mtproto / 49
ls /root/ovh10g/ | wc -l                     # 12 parts
```
Read this file fully before any action. Do NOT re-run any benchmark already recorded above.

## PHASE 1 — Diagnostic: why does bot CDN truncate? (~30 min, no upload needed)
Goal: read FuYGddJNWTGh's 640 chunks DIRECTLY via Bot API (bypassing anbar's streaming
generator) to isolate whether truncation is Telegram-side or our code.

Script sketch (`/tmp/diag_bot_chunks.py`, run on host with .env sourced):
1. Read manifest for FuYGddJNWTGh from anbar DB (`/opt/anbar/data/anbar.db`,
   objects/chunks tables — check schema first with `.schema`).
2. For each chunk i: `getFile(file_id)` → GET
   `https://api.telegram.org/file/bot<TOKEN>/<path>`. Log per chunk:
   index, size, latency_ms, http_status, error_text. Append JSONL to
   `/tmp/diag_bot_chunks.jsonl` after EVERY chunk (crash-safe).
3. Run until first failure or all 640 done. Expected outcomes:
   - Fails at consistent chunk count (~90–170 ≈ 1.4–2.8GB) with 429/5xx → Telegram-side
     pacing; note exact error and reset-after time.
   - All 640 succeed individually → truncation bug is OUR streaming generator
     (download.py); fix there instead.
4. If 429s: record `retry_after` values; compute viable sustained rate =
   bytes_until_first_429 / elapsed. This number decides if hybrid needs pacing/2nd token.

Deliverable: one-line verdict + the JSONL log path.

## PHASE 2 — Fix or accept (~depends on Phase 1)
- If OUR bug: add per-chunk retry w/ exponential backoff inside download.py stream()
  generator (only for bot backend path), re-test full GET of FuYGddJNWTGh via curl.
- If TELEGRAM pacing: decide with Hossein between (a) accept lower-but-still-fast
  sustained rate, (b) second bot token round-robin, (c) cache-first strategy.

## PHASE 3 — Implement hybrid store (~half session)
1. `config.py`: `chunk_size_mb` stays env-driven; set prod to 16 when enabling hybrid.
   Add `hybrid_enabled: bool = False` + admin runtime toggle `hybrid_enabled` in
   runtime.SPEC (Hossein wants admin-togglable features).
2. `ObjectRef`/Chunk: optional `bot_file_id: str | None`.
3. New lightweight module `src/anbar/storage/bot_harvester.py`: background task started
   per-upload (and globally at startup) doing long-poll `getUpdates`
   (allowed_updates=["channel_post"]), matching posted docs to in-flight uploads by size
   sequence, writing bot_file_id into the manifest row as they arrive. Must tolerate
   restarts (offset persisted in kv).
4. `mtproto_backend.store()`: unchanged (still posts doc to MT channel). After store,
   harvester fills bot_file_id asynchronously; upload response returns immediately —
   bot_file_id backfilled later (download falls back until then). Alternative simpler
   v1: block up to N s waiting for each update before returning ref — MEASURE BOTH?
   Start with blocking v1 (deterministic manifests) since updates arrive <1s.
5. `download.py` stream()/filling_stream(): if `chunk.bot_file_id` present AND
   hybrid_enabled → fetch via Bot API getFile (with retry/backoff from Phase 2 findings);
   else existing mtproto open().
6. Tests: FakeBackend unaffected; new unit tests for harvester matching + fallback logic.
7. SCAN-CLEAN grep, commit, push, build image, deploy, smoke test 100MB object end-to-end.

## PHASE 4 — Full hybrid benchmark (the one Hossein asked for)
- Set ANBAR_CHUNK_SIZE_MB=16, hybrid ON, backend mtproto.
- Upload fresh 10GB from /root/ovh10g via bench harness (loopback, KEEP=1):
  record upload wall time (expect ≈729s + small harvester overhead) and verify every
  chunk got bot_file_id (count in DB = 640).
- Download full object via signed URL; record wall time, per-600s progress lines,
  sha256 vs b626371c… Expect >>5.21 MB/s if Phase 1/2 resolved truncation.
- Also run a 100MB and 1GB hybrid ladder for README consistency.
- Restore env (chunk 49, hybrid per Hossein's choice), redeploy.
- Update README: replace/add rows under the A/B section; SCAN-CLEAN; push.

## Rollback & safety notes
- Any breakage: `ANBAR_BACKEND=bot` + recreate = known-good old path; hybrid toggle off
  returns pure-mtproto behavior without code changes.
- Never print BOT_TOKEN/API keys/secrets; [REDACTED] everywhere.
- Foreground command cap 600s — run benches background+notify like before.
- Keep both existing test objects unless Hossein says delete.
