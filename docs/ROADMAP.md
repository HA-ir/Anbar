# Roadmap

## Phases

| Phase | Branch | Scope | Exit criteria | Status |
|-------|--------|-------|---------------|--------|
| F1 | `f1-skeleton` | repo, config, SQLite, app factory, Docker, CI | `docker build` + healthz + 15 tests green | ✅ v0.1.0 |
| F2 | `f2-bot-backend` | Bot storage backend (private channel), upload (multipart + raw), chunking + manifest, object ids | 10–15 MB file uploaded to Telegram, metadata correct, resume works | ⏳ |
| F3 | `f3-download` | streaming download, Range (incl. multi-chunk), `/f/{id}/info`, Content-Disposition | curl Range returns exact bytes; sha256 matches upload | ⏳ |
| F4 | `f4-auth` | API keys, HMAC signed URLs (±expiry), runtime toggle, rate limits, DELETE, link minting, objects list | security checklist in DEPLOY passes; toggle on/off without restart | ⏳ |
| F5 | `f5-mtproto` | Telethon backend (dedicated account, Saved Messages), 2 GB, backend selection at runtime | file > 100 MB uploaded/downloaded; bot & mtproto coexist | ⏳ |
| F6 | `f6-hardening` | full CLI (link/list/auth/rotate-secret), LRU cache wired, docs final, production deploy, load test | golden test end-to-end; `v1.0` tag | ⏳ |

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

## Open questions

- Domain for the public deployment (candidate: `d.example.com`) — F6.
- Dedicated MTProto account availability — needed only at F5.
- Optional web dashboard — explicitly out of scope for v1; revisit after v1.0.

## v1.0 definition of done

1. `git log` shows six phases, CI green, tag `v1.0`.
2. Golden test on production: 150 MB upload → direct link → curl download →
   sha256 matches → local disk growth ≈ 0.
3. `anbarctl auth off` → unsigned links work; `anbarctl auth on` → 401 without signature.
4. A stranger can deploy from a fresh machine in < 15 min following DEPLOY.md.