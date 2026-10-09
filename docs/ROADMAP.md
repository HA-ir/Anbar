# Roadmap

## Phases

| Phase | Branch | Scope | Exit criteria | Status |
|-------|--------|-------|---------------|--------|
| F1 | `f1-skeleton` | repo, config, SQLite, app factory, Docker, CI | `docker build` + healthz + 15 tests green | ✅ v0.1.0 |
| F2 | `f2-bot-backend` | Bot storage backend (private channel), upload (multipart + raw), chunking + manifest, object ids | 10–15 MB file uploaded to Telegram, metadata correct, resume works | ✅ (resume → F3) |
| F3 | `f3-download` | streaming download, Range (incl. multi-chunk), `/f/{id}/info`, Content-Disposition | curl Range returns exact bytes; sha256 matches upload | ✅ |
| F4 | `f4-auth` | API keys, HMAC signed URLs (±expiry), runtime toggle, DELETE, link minting, objects list, anbarctl CLI | security checklist in DEPLOY passes; toggle on/off without restart | ✅ (rate limits → F6) |
| F5 | `f5-mtproto` | Telethon backend (dedicated account, Saved Messages), 2 GB, backend selection at runtime | file > 100 MB uploaded/downloaded; bot & mtproto coexist | ✅ v0.5.0 (golden needs a real account) |
| F6 | `f6-hardening` | rate limiting (SQLite), LRU cache (off by default), load test, docs final, production deploy | golden test end-to-end; `v1.0` tag | ✅ v0.6.0 — deployed to a live host (v1.0 tag deferred) |
| F7 | `f7-web-ui` | web UI (RTL): login with admin key → signed session cookie; list / upload / download / delete / share | UI E2E green: cookie-auth upload+download, tamper rejected, logout invalidates | ✅ v0.7.0 — E2E 14/14 on prod |
| F9 | `main` | v0.8.x–v0.9.x: URL ingest, pw links, QR, rename, multi-select, per-link cap, gallery, PWA share target, folder upload, API-key UI, pretty slugs (`/f/<name>`), never-expire links (`ttl=0`), bulk share, selection UX | each release: tests+ruff green → build `f<N>` → deploy | ✅ v0.9.5 |
| F10 | `main` | **v0.10**: link registry + instant revoke · trash (soft delete/restore/7-day auto-purge) · streaming bulk ZIP · type filter · video poster frames | 134 tests green; live smoke on prod; deployed | ✅ v0.10.0 |
| — | `main` | **v0.10.1–v0.10.5** (hardening & UX): mobile responsive · pw unlock page w/ hidden sig+exp (keyed-HMAC fix) · link manager modal in-app · live-only links list · shared albums (`/f/a/<token>`) · per-link download counters · gallery audio/PDF previews | 162 tests green; live smoke on prod each release | ✅ v0.10.5 |
| F11 | `main` | **v0.14.x–v0.15.x**: Self-Healing Disaster Recovery · Client-Side True ZK · Hybrid BotPool + MTProto backend · Video seeking & subtitle extraction · Resumable queue | 485 tests green; live on prod | ✅ v0.15.58 |
| F12 | `main` | **v0.15.59–v0.15.60**: Telegram Bot Webhook & Ingest Engine · FastTelethon MTProto Pipelining (5–15+ MB/s, 1–8 workers) · Strict Owner Authorization & Silent Drop · Same-Name Directory Support · Modular Settings Cards Overhaul · S3-Compatible REST Gateway (SigV4, SigV2, Multi-Delete) | 538 tests green; live on prod | ✅ v0.15.60 |

## Completed Milestones

- **MTProto & Hybrid Mode on prod** — fully configured and operational with automated credential verification, session borrowing, and multi-bot token distribution.
- **Web Dashboard & Drive** — fully delivered with responsive mobile layouts, bilingual support, media playback, folder drill-down, and move browser.
- **S3 Protocol Gateway** — fully implemented at `/s3/{bucket}/{key}` with SigV4/SigV2/Pre-signed URL authentication, ListObjectsV2, and multi-object deletion.
- **Telegram Bot Ingestion** — webhook receiver, Mode A/B/C streaming ingestion, in-chat progress updates, and command handling.

## Open items (Future Enhancements)

- **True At-Rest Chunk Encryption**: Extend caption encryption to encrypt raw file chunks with AES-256-GCM before dispatching to Telegram storage.
- **Automated Docker Builder Prune**: Automate builder cache pruning in deployment pipelines to keep disk usage lean on small production VPS nodes.

Each phase: branch → small commits (`fN: <summary>`) → tests green → merge to
`main` → tag `v0.N.0`.

## Decisions log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-20 | Name: **anbar** | Persian "warehouse goods pass through" — matches zero-retention design |
| 2026-08-20 | FastAPI over Flask | async-native: needed for concurrent Telegram streams |
| 2026-08-20 | Raw httpx for Bot API (no bot framework) | we only need sendDocument/getFile; a framework would add weight |
| 2026-08-20 | SQLite (WAL) over Postgres | metadata is KB-scale; zero-ops wins for portability |
| 2026-08-20 | HMAC signed URLs over JWT | stateless, no token store, trivially revocable via expiry |
| 2026-08-20 | Private channel (bot backend), Saved Messages (mtproto) | groups visible to members; bot cannot DM itself |
| 2026-08-20 | One-element manifest for small files | single code path for blob & chunked objects |
| 2026-08-20 | Chunking layer above backends | removes hard size ceiling; enables resumable uploads |
| 2026-08-20 | Bot backend first, MTProto selectable in F5 | user decision: simple first, 2 GB later, user picks per deployment |
| 2026-08-22 | Telethon (not Pyrogram/MTProto-raw) for F5 | async-native (matches FastAPI), maintained, session-file model fits "login once via anbarctl, server reuses" |
| 2026-08-22 | MTProto chunk cap 49 MB (tunable) | blobs = messages in Saved Messages; bigger chunks → fewer messages, still well under 2 GB |
| 2026-08-22 | Fixed-window rate limits in SQLite (no Redis) | matches zero-ops/SQLite-only architecture; per-(IP,obj) download + per-key upload, `429` + `Retry-After` |
| 2026-08-22 | LRU disk cache **off by default** | user decision: purest zero-retention stays the default; cache is evictable scratch space, never persistent storage |
| 2026-08-22 | Download streaming stays O(chunk) | no per-request `fetched` dict / whole-object buffering; load test (20×48 MB) proves bounded RSS |
| 2026-09-11 | UI auth = signed session cookie (HMAC), not JWT | stateless (no token table), reuses `hmac_secret`; value is `{exp}:{tag}:{sig}` — raw key never stored client-side; HttpOnly + SameSite=Lax + Secure |
| 2026-09-11 | UI gate = admin key only | it's a personal owner tool (full list + delete + share); uploader keys stay API-only |

## Decisions log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-20 | Name: **anbar** | Persian "warehouse goods pass through" — matches zero-retention design |
| 2026-08-20 | FastAPI over Flask | async-native: needed for concurrent Telegram streams |
| 2026-08-20 | Raw httpx for Bot API (no bot framework) | we only need sendDocument/getFile; a framework would add weight |
| 2026-08-20 | SQLite (WAL) over Postgres | metadata is KB-scale; zero-ops wins for portability |
| 2026-08-20 | HMAC signed URLs over JWT | stateless, no token store, trivially revocable via expiry |
| 2026-08-20 | Private channel (bot backend), Saved Messages (mtproto) | groups visible to members; bot cannot DM itself |
| 2026-08-20 | One-element manifest for small files | single code path for blob & chunked objects |
| 2026-08-20 | Chunking layer above backends | removes hard size ceiling; enables resumable uploads |
| 2026-08-20 | Bot backend first, MTProto selectable in F5 | user decision: simple first, 2 GB later, user picks per deployment |
| 2026-08-22 | Telethon (not Pyrogram/MTProto-raw) for F5 | async-native (matches FastAPI), maintained, session-file model fits "login once via anbarctl, server reuses" |
| 2026-08-22 | MTProto chunk cap 49 MB (tunable) | blobs = messages in Saved Messages; bigger chunks → fewer messages, still well under 2 GB |
| 2026-08-22 | Fixed-window rate limits in SQLite (no Redis) | matches zero-ops/SQLite-only architecture; per-(IP,obj) download + per-key upload, `429` + `Retry-After` |
| 2026-08-22 | LRU disk cache **off by default** | user decision: purest zero-retention stays the default; cache is evictable scratch space, never persistent storage |
| 2026-08-22 | Download streaming stays O(chunk) | no per-request `fetched` dict / whole-object buffering; load test (20×48 MB) proves bounded RSS |
| 2026-09-11 | UI auth = signed session cookie (HMAC), not JWT | stateless (no token table), reuses `hmac_secret`; value is `{exp}:{tag}:{sig}` — raw key never stored client-side; HttpOnly + SameSite=Lax + Secure |
| 2026-09-11 | UI gate = admin key only | it's a personal owner tool (full list + delete + share); uploader keys stay API-only |
| 2026-10-08 | FastTelethon MTProto Pipelining | Low-level concurrent `upload.GetFileRequest` over DC senders overcomes single-stream ~1.1 MB/s ceiling to achieve 5–15+ MB/s |
| 2026-10-09 | External S3 API Protocol Bridge | Map standard AWS SigV4/SigV2 headers to internal authentication and support multi-object XML deletions |

## v1.0 definition of done

1. `git log` shows core phases complete, CI green, tag `v0.15.60` (or `v1.0`).
2. Golden test on production: multi-GB upload → direct link → curl download →
   sha256 matches → local disk growth ≈ 0.
3. `anbarctl auth off` → unsigned links work; `anbarctl auth on` → 401 without signature.
4. S3 protocol endpoints validated with standard external S3 clients.
5. A stranger can deploy from a fresh machine in < 15 min following DEPLOY.md.