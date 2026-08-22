# Anbar

**Telegram-backed object storage with zero local file retention.**

Anbar is a two-way proxy (upload + download) between your users and Telegram.
Files live in the Telegram cloud; only a few kilobytes of metadata per object
remain on your server (SQLite, WAL mode). Users get plain direct-download links
— nothing in a URL reveals where the bytes actually live.

> The name: *anbar* (انبار) — a warehouse where goods pass through, not one where they stay.

## Status

| Phase | Scope | Status |
|-------|-------|--------|
| F1 | Skeleton: repo, config, SQLite, app factory, Docker, CI | ✅ `v0.1.0` |
| F2 | Bot storage backend + upload endpoints (multipart + raw) | ✅ `v0.2.0` |
| F3 | Streaming download + HTTP Range + object info | ✅ `v0.3.0` |
| F4 | Auth: API keys, HMAC signed URLs, runtime toggle, anbarctl CLI | ✅ `v0.4.0` |
| F5 | MTProto backend (up to 2 GB, user-selectable) | ✅ `v0.5.0` |
| F6 | Hardening: rate limiting, LRU cache, load test, docs, production deploy | ✅ `v0.6.0` — deployed |
| F7 | Web UI (RTL): login → signed session cookie; list / upload / download / delete / share | ✅ `v0.7.0` |
| F8 | Bilingual UI (fa/en), dark/light theme, runtime settings panel, speed-test docs, cache master-switch fix | ✅ `v0.8.1` |

## Why

- **Disk relief** — the server holds metadata, not files. A 1 TB of objects ≈ a few MB of SQLite.
- **Direct links** — `https://host/f/<id>` works with curl, browsers, any HTTP client. Range/seek supported.
- **No hard size ceiling** — large files are chunked into ≤16 MB parts stored individually; manifests live in SQLite. Uploads are resumable.
- **Auth on/off at runtime** — no restart needed; toggle via API or `anbarctl`.
- **Portable** — Docker-first. One `docker compose up` on any server. Per-deploy Telegram channel/account keeps instances independent.
- **Pluggable backends** — `bot` (F2), `mtproto` (F5), with room for S3/local fallback behind the same interface.

## Hardening (F6)

- **Rate limiting** — fixed-window counters in SQLite (no Redis). Downloads are
  limited per `(IP, object)`; uploads per API key. Over-limit requests get
  `429` + `Retry-After`. Limits are per-minute ceilings, `0` disables.
- **Optional LRU cache** — OFF by default. When enabled, whole objects are kept
  as *evictable* temp files (bounded by `ANBAR_CACHE_MAX_MB`, LRU-evicted) under
  the `data` volume so repeat downloads skip the Telegram round-trip. The
  zero-retention guarantee is unchanged: cached files are scratch space that can
  be evicted (or the cache deleted) at any time, not persistent storage.
- **Streaming stays O(chunk)** — a download never buffers the whole object; a
  concurrent load test (20 × 48 MB) verifies byte-exactness and bounded memory.

## Web UI (F7)

A minimal RTL (Persian) single page at the site root (`/`):

- **Login** — enter the **admin** key. On success a signed session cookie
  (`anbar_session`, `HttpOnly` + `SameSite=Lax` + `Secure`) is set. The raw key
  is *not* stored in the browser afterward — every same-origin request carries
  the cookie, and `whoami` resolves the role from it.
- **List / upload / download / delete / share** — the page reuses the existing
  JSON API (`/api/v1/*`, `/f/{id}`), so storage logic is not duplicated. Upload
  supports drag&drop + multiple files with a progress bar; "link" mints a
  24-hour signed URL; downloads stream through the same `/f/{id}` route.
- **Stateless sessions** — the cookie is `HMAC-SHA256(secret, exp:tag)`, so a
  tampered cookie fails the signature check and the login endpoint is
  rate-limited per IP. Logout clears the cookie server-side.

## Runtime settings (F8)

Operational settings can be changed **without a restart** — from the Web UI
settings panel or the admin API — and are persisted in SQLite (`kv` table),
so they survive container restarts.

- **Settings panel** (`/` → تنظیمات) — bilingual (Persian / English) UI with a
  dark/light theme toggle. Changing a value POSTs to the settings API; the
  panel shows the effective value and can reset any key to its default.
- **Admin API** — `GET /api/v1/admin/settings` (defaults, persisted
  overrides, effective values), `POST /api/v1/admin/settings`
  (`{"rate_upload": 20, ...}`), `POST /api/v1/admin/settings/reset`
  (`{"keys": [...]}`) — all admin-key only.

| Setting | Default | Notes |
|---------|---------|-------|
| `rate_upload` | 20 | uploads / min per API key; `0` = unlimited |
| `rate_download` | 30 | downloads / min per (IP, object); `0` = unlimited |
| `cache_mb` | (env) | LRU cache budget; only takes effect when the cache master switch is ON (below) |

### Cache master switch (F8 fix)

`ANBAR_CACHE_ENABLED` (env, `.env`) is the **master switch** for the on-disk
LRU cache. When it is `false`, no cache is ever created — not at startup and
not when `cache_mb` is changed at runtime. Runtime `cache_mb` changes only
re-size the cache **if the master switch is on**; otherwise they are stored
but inert, and the Web UI shows the cache section as disabled. This
preserves the zero-retention guarantee: with the default configuration anbar
writes **nothing** to disk except the SQLite metadata database.

## Speed test (v0.8.3, bot backend)

Measured **2026-08-22** on a production deployment
(`anbar.example.com`, nginx + Cloudflare, `bot` backend, one Telegram account,
16 MB chunk ceiling) with a Python client directly on `127.0.0.1:8317`.
**Cache OFF** throughout (master switch default) — every number below is a
real Telegram round-trip.

| Size | Upload | Download 1st GET | Download 2nd GET |
|------|--------|------------------|------------------|
| 0.5 MB | 0.25 s — 2.0 MB/s | 0.40 s — 1.2 MB/s | 0.05 s — 10.4 MB/s |
| 1.9 MB | 0.32 s — 5.9 MB/s | 0.75 s — 2.5 MB/s | 0.10 s — 18.3 MB/s |
| 8 MB | 0.74 s — 10.8 MB/s | 2.11 s — 3.8 MB/s | 0.10 s — 82.2 MB/s |
| 19 MB (2 chunks) | 1.27 s — 15.0 MB/s | 1.86 s — 10.2 MB/s | 0.20 s — 95.7 MB/s |
| 45 MB (3 chunks) | 1.97 s — 22.9 MB/s | 5.63 s — 8.0 MB/s | 0.46 s — 98.9 MB/s |
| 100 MB (7 chunks) | 7.60 s — 13.2 MB/s | 8.56 s — 11.7 MB/s | 1.29 s — 77.8 MB/s |
| 1 GB (64 chunks) | 206.4 s — 4.96 MB/s | 101.4 s — 10.1 MB/s | 12.1 s — 84.9 MB/s |
| 4 × 8 MB parallel | 2.19 s — 14.6 MB/s agg | — | — |

Through the public HTTPS path (Cloudflare + TLS + nginx), signed share links:
0.5 MB → 0.27 s (1.9 MB/s), 8 MB → 1.20 s (6.6 MB/s).

**How to read this**

- **Upload** tops out around **15–23 MB/s**: each ≤16 MB chunk is a separate
  Telegram `upload` round-trip, so multi-chunk files add a fixed per-chunk
  latency on top of the wire time.
- **First download** is the cold Telegram CDN path: 1.2–10 MB/s depending on
  size (small files pay the fixed round-trip; large files stream).
- **Second download** looks fast, but with the cache OFF it is *not* anbar
  caching — it is **Telegram's own CDN** serving the blob it just delivered
  (same account, warm edge). The two numbers bound the real-world range:
  cold ≈ 1–10 MB/s, warm-CDN up to ~100 MB/s on this link.
- **Parallel uploads** (4 × 8 MB): 4/4 succeeded, 14.6 MB/s aggregate.
  Telegram rate-limits per *account*, not per server, so a single bot account
  caps sustained concurrency — heavy concurrency hits `FloodWait`, which
  v0.8.3 absorbs by waiting (see below). The `mtproto` backend (F5) does
  not have this per-request API ceiling.
- **100 MB** (7 chunks) uploads cleanly at 13.2 MB/s and the cold download
  runs at 11.7 MB/s — the multi-chunk path scales fine in this range.
- **1 GB now uploads on the `bot` backend** (v0.8.3 flood pacing, below):
  206 s at 4.96 MB/s sustained, cold download 10.1 MB/s, warm CDN 84.9 MB/s.
  It works because anbar now *waits out* the account's flood window instead
  of giving up — the cost is that the sustained rate drops to ~5 MB/s.
- SHA-256 verified on every downloaded object (all `sha_ok=true`).

### Large-file uploads on the `bot` backend (v0.8.3 flood pacing)

A 1 GB object is 64 × 16 MB `sendDocument` calls into the **same channel**
on the **same bot account**. Telegram rate-limits messages per *chat*:
after ~20 consecutive posts the API starts answering
`429 Too Many Requests: retry after 30–33 s` for a sustained window.
Measured on the live channel (2026-08-22):

- 20 consecutive 16 MB posts: all accepted, but individual calls stalled up
  to **133 s** (server-side throttling) — 20 posts already consume a full
  rate window.
- Continuing past 20: every further chunk fails with 429
  (`retry_after` 33 → 9 s over ~25 attempts).
- Telegram's own transient **502/500** responses (sometimes
  description-less) also occur mid-burst.

**v0.8.3 makes this survivable** instead of failing it:

1. **Pacing** — each `sendDocument` waits at least `ANBAR_FLOOD_SEND_GAP_S`
   (default 1.1 s) after the previous one, so chunks are spread instead of
   bursting, which shortens the 429 windows.
2. **Patient flood waits** — a 429/402 (and transient 500/502) no longer
   fails the chunk after 5 tries. Anbar honours `retry_after` and keeps
   waiting until a per-upload budget `ANBAR_FLOOD_BUDGET_S` (default
   2400 s) is exhausted *cumulatively*; only then does the upload fail,
   with a **504** (retryable) plus rollback of the already-posted chunks.
3. **Rollback** — on any mid-way failure the posted `file_id`s are deleted
   from the channel, so a failed 1 GB upload leaves no orphan blobs.

Measured 1 GB upload on the live channel: **206 s ≈ 3.5 min** sustained
(4.96 MB/s) — 64 chunks at a ~3 s average post + flood waits. The first
~20 chunks go near line rate (15–23 MB/s); the tail runs at whatever pace
the account's flood window allows. Downloads are unaffected (64 ×
`getFile` pulls do not hit the per-chat send limit): cold 10.1 MB/s,
warm CDN 84.9 MB/s.

> **Rule of thumb (bot backend):** any size up to `max_upload_mb` now
> works; expect **~3.5 min per GB** of sustained upload time. If you need
> higher sustained throughput, the `mtproto` backend (F5) uses a single
> MTProto session (2 GB ceiling, no per-message API ceiling) and is the
> faster path for large files.

## Core concepts

- **Object** — an uploaded file, referenced by a short base62 `id`. May consist of one blob (≤ backend ceiling) or many chunks (manifest).
- **Backend** — where the bytes live. `bot` = Telegram Bot API into a **private channel** the bot administers (≤20 MB per blob). `mtproto` = MTProto user session into Saved Messages (≤2 GB per blob).
- **Manifest** — JSON in SQLite mapping an object to its ordered chunks. A single-blob object has a one-element manifest; the download/upload code paths are identical either way.
- **Signed URL** — `{base}/f/{id}?e=<expiry>&s=<HMAC-SHA256>` used when auth is enabled.

## Repository layout

```
src/anbar/
├── main.py           # FastAPI app factory (backend injectable for tests)
├── config.py         # env-driven settings (pydantic-settings), validated
├── db.py             # SQLite WAL metadata store (objects + kv + rate tables)
├── cache.py          # F6: optional LRU disk cache (off by default)
├── ratelimit.py      # F6: fixed-window rate limits (SQLite, no Redis)
├── cli.py            # anbarctl — operational CLI
├── api/
│   ├── upload.py     # POST /api/v1/upload, /upload/raw
│   ├── download.py   # GET /f/{id}, /f/{id}/info
│   └── admin.py      # GET /api/v1/admin/status (+ auth toggle)
└── storage/
    ├── base.py       # StorageBackend interface + FakeBackend (test contract)
    ├── bot_backend.py# F2: Bot API via httpx (no bot framework)
    └── mtproto_backend.py  # F5: Telethon (dedicated account, 2 GB)
tests/                # 67 passing — API golden tests, storage contract, hardening
docker/               # Dockerfile (non-root, healthcheck), compose.yaml
nginx/anbar.conf.example
docs/                 # ARCHITECTURE, API, DEPLOY, ROADMAP
.env.example
```

## Quick start (development)

```bash
uv sync --extra dev
uv run pytest -q          # 67 passing
uv run anbarctl version   # anbar 0.6.0
```

Run a local instance with the in-memory backend (no Telegram needed):

```bash
ANBAR_BACKEND=fake ANBAR_BASE_URL=http://127.0.0.1:8317 \
  uv run uvicorn anbar.main:create_app --factory --port 8317
curl http://127.0.0.1:8317/healthz
```

## Deploy (from F2 onward)

```bash
cp .env.example .env      # bot token, base URL, keys
cd docker && docker compose up -d
curl http://127.0.0.1:8317/healthz
```

Put Caddy or your existing Nginx in front (TLS). See [docs/DEPLOY.md](docs/DEPLOY.md).

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — layers, data flow, chunking, storage locations
- [API reference](docs/API.md) — every endpoint, auth matrix, error codes
- [Deployment guide](docs/DEPLOY.md) — Docker, Caddy/Nginx, secrets, ops runbook
- [Roadmap](docs/ROADMAP.md) — phase details, decisions, open questions

## Git conventions

- `main` is always deployable (CI green).
- One branch per phase: `f2-bot-backend` … `f6-hardening`.
- Commits: `fN: <imperative summary>` (prefix = phase).
- Each merge to `main` is tagged `v0.N.0`; GA is `v1.0`.
- CI (`.github/workflows/ci.yaml`): ruff + pytest + Docker smoke (healthz).
- **Secrets never enter the repo** — only `.env.example` with placeholders.

## Security notes (short version)

- Links are guessable without auth → **auth is ON by default**.
- HMAC URLs: secret rotation supported (`anbarctl rotate-secret`, F4).
- Service binds to loopback only; reverse proxy adds TLS.
- Container runs non-root with `no-new-privileges`.
- API keys are redacted in logs (F4 checklist item).

## Non-goals

- Folder trees / drive-style UI (flat objects only)
- Online editing, versioning, granular sharing
- Full web dashboard (REST API + CLI first; dashboard later, if ever)