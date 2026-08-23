# Roadmap

## Phases

| Phase | Branch | Scope | Exit criteria | Status |
|-------|--------|-------|---------------|--------|
| F1 | `f1-skeleton` | repo, config, SQLite, app factory, Docker, CI | `docker build` + healthz + 15 tests green | ✅ v0.1.0 |
| F2 | `f2-bot-backend` | Bot storage backend (private channel), upload (multipart + raw), chunking + manifest, object ids | 10–15 MB file uploaded to Telegram, metadata correct, resume works | ✅ (resume → F3) |
| F3 | `f3-download` | streaming download, Range (incl. multi-chunk), `/f/{id}/info`, Content-Disposition | curl Range returns exact bytes; sha256 matches upload | ✅ |
| F4 | `f4-auth` | API keys, HMAC signed URLs (±expiry), runtime toggle, DELETE, link minting, objects list, anbarctl CLI | security checklist in DEPLOY passes; toggle on/off without restart | ✅ (rate limits → F6) |
| F5 | `f5-mtproto` | Telethon backend (dedicated account, Saved Messages), 2 GB, backend selection at runtime | file > 100 MB uploaded/downloaded; bot & mtproto coexist | ✅ v0.5.0 (golden needs a real account) |
| F6 | `f6-hardening` | rate limiting (SQLite), LRU cache (off by default), load test, docs final, production deploy | golden test end-to-end; `v1.0` tag | ✅ v0.6.0 — deployed (`anbar.example.com`) — `v1.0` tag deferred at user request |
| F7 | `f7-web-ui` | web UI (RTL): login with admin key → signed session cookie; list / upload / download / delete / share | UI E2E green: cookie-auth upload+download, tamper rejected, logout invalidates | ✅ v0.7.0 — E2E 14/14 on prod |
| F9 | `main` | v0.8.x–v0.9.x: URL ingest, pw links, QR, rename, multi-select, per-link cap, gallery, PWA share target, folder upload, API-key UI, pretty slugs (`/f/<name>`), never-expire links (`ttl=0`), bulk share, selection UX | each release: tests+ruff green → build `f<N>` → deploy | ✅ v0.9.5 |
| F10 | `main` | **v0.10**: link registry + instant revoke · trash (soft delete/restore/7-day auto-purge) · streaming bulk ZIP · type filter · video poster frames | 134 tests green; live smoke on prod; deployed | ✅ v0.10.0 |
| — | `main` | **v0.10.1–v0.10.5** (hardening & UX): mobile responsive · pw unlock page w/ hidden sig+exp (keyed-HMAC fix) · link manager modal in-app · live-only links list · shared albums (`/f/a/<token>`) · per-link download counters · gallery audio/PDF previews | 162 tests green; live smoke on prod each release | ✅ v0.10.5 |

## Open items (post-v0.10.5)

- **MTProto on prod** — `/app/secrets` still empty; needs a dedicated
  account + `api_id`/`api_hash`. Deferred by the maintainer until the bot-backend
  path has been exercised more.
- README benchmark table records the 2026-08-22 bot-backend numbers
  (0.5 MB–1 GB); re-run after switching backends or chunk size.
- Optional future: S3/local backend behind the same interface (design only).

Each phase: branch → small commits (`fN: <summary>`) → tests green → merge to
`main` → tag `v0.N.0`.

## Decisions log

| Date | Decision | Rationale |
|------|----------|-----------|
| — | Name: **anbar** | Persian "warehouse goods pass through" — matches zero-retention design |
| — | FastAPI over Flask | async-native: needed for concurrent Telegram streams |
| — | Raw httpx for Bot API (no bot framework) | we only need sendDocument/getFile; a framework would add weight |
| — | SQLite (WAL) over Postgres | metadata is KB-scale; zero-ops wins for portability |
| — | HMAC signed URLs over JWT | stateless, no token store, trivially revocable via expiry |
| — | Private channel (bot backend), Saved Messages (mtproto) | groups visible to members; bot cannot DM itself |
| — | One-element manifest for small files | single code path for blob & chunked objects |
| — | Chunking layer above backends | removes hard size ceiling; enables resumable uploads |
| — | Bot backend first, MTProto selectable in F5 | user decision: simple first, 2 GB later, user picks per deployment |
| — | Telethon (not Pyrogram/MTProto-raw) for F5 | async-native (matches FastAPI), maintained, session-file model fits "login once via anbarctl, server reuses" |
| — | MTProto chunk cap 49 MB (tunable) | blobs = messages in Saved Messages; bigger chunks → fewer messages, still well under 2 GB |
| — | Fixed-window rate limits in SQLite (no Redis) | matches zero-ops/SQLite-only architecture; per-(IP,obj) download + per-key upload, `429` + `Retry-After` |
| — | LRU disk cache **off by default** | user decision: purest zero-retention stays the default; cache is evictable scratch space, never persistent storage |
| — | Download streaming stays O(chunk) | no per-request `fetched` dict / whole-object buffering; load test (20×48 MB) proves bounded RSS |
| — | UI auth = signed session cookie (HMAC), not JWT | stateless (no token table), reuses `hmac_secret`; value is `{exp}:{tag}:{sig}` — raw key never stored client-side; HttpOnly + SameSite=Lax + Secure |
| — | UI gate = admin key only | it's a personal owner tool (full list + delete + share); uploader keys stay API-only |

## Open questions

- Domain for the public deployment (candidate: `d.example.com`) — F6.
- Dedicated MTProto account + `api_id`/`api_hash` — needed for the F5 golden test and the real deploy (F6).
- Optional web dashboard — explicitly out of scope for v1; revisit after v1.0.

## v1.0 definition of done

1. `git log` shows six phases, CI green, tag `v1.0`.
2. Golden test on production: 150 MB upload → direct link → curl download →
   sha256 matches → local disk growth ≈ 0.
3. `anbarctl auth off` → unsigned links work; `anbarctl auth on` → 401 without signature.
4. A stranger can deploy from a fresh machine in < 15 min following DEPLOY.md.