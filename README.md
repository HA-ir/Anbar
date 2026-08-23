# Anbar

[![CI](https://github.com/HA-ir/Anbar/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/HA-ir/Anbar/actions/workflows/ci.yaml)
[![Docker image](https://img.shields.io/badge/image-ghcr.io%2FHA--ir%2FAnbar-blue)](https://github.com/HA-ir/Anbar/pkgs/container/anbar)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

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
| v0.9.x | URL ingest · pw-protected links · QR · rename · multi-select · per-link download cap · gallery view · metadata export · PWA share target · folder upload · API-key mgmt UI · pretty link slugs (`/f/<name>`) · never-expiring links (`ttl=0`) · bulk share · selection UX polish | ✅ `v0.9.5` |
| v0.10 | Link registry + instant revoke · Trash (soft delete / restore / auto-purge 7d) · streaming bulk ZIP · type filter · video poster frames | ✅ `v0.10.0` |
| v0.10.x | Mobile responsive · pw unlock page (hidden sig+exp, eye toggle, keyed-HMAC fix) · link manager modal in-app · live-only links list + per-link download counters · shared albums (`/f/a/<token>`) · gallery audio/PDF previews | ✅ `v0.10.5` — live |

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

## Speed test (v0.10.8, bot backend)

Measured **2026-08-23** on a small VPS deployment (nginx + Cloudflare in
front, `bot` backend, 16 MB chunk ceiling) with
[scripts/bench.py](scripts/bench.py) directly on the loopback port.
**Cache OFF** throughout (master switch default) — every number below is a
real Telegram round-trip. Expect similar-but-different numbers on your host;
the ratios (2nd GET ≫ 1st GET) are what matter.

| Size | Upload | Download 1st GET | Download 2nd GET |
|------|--------|------------------|------------------|
| 1 MB | 0.35 s — 2.8 MB/s | 0.59 s — 1.7 MB/s | 0.18 s — 5.7 MB/s |
| 8 MB | 0.85 s — 9.4 MB/s | 1.86 s — 4.3 MB/s | 0.32 s — 25.2 MB/s |
| 45 MB | 4.06 s — 11.1 MB/s | 5.11 s — 8.8 MB/s | 0.90 s — 49.8 MB/s |
| 100 MB | 12.37 s — 8.1 MB/s | 9.94 s — 10.1 MB/s | 1.88 s — 53.3 MB/s |

Re-run it against your own instance:

```bash
export ANBAR_BASE_URL=http://127.0.0.1:8567 ANBAR_ADMIN_KEY=***
.venv/bin/python scripts/bench.py --sizes 1 8 45
```

**How to read this**

- **Upload** runs at **~3–11 MB/s** on the `bot` backend: each ≤16 MB chunk is
  a separate Telegram `sendDocument` round-trip plus the flood-pacing gap, so
  multi-chunk files add fixed per-chunk latency on top of wire time.
- **First download** is the cold Telegram CDN path: ~2–10 MB/s depending on
  size (small files pay the fixed round-trip; large files stream).
- **Second download** looks fast, but with the cache OFF it is *not* anbar
  caching — it is **Telegram's own CDN** serving the blob it just delivered
  (same account, warm edge). The two numbers bound the real-world range:
  cold ≈ 2–10 MB/s, warm-CDN up to ~50 MB/s on this link.
- The multi-chunk path scales fine: 100 MB (7 chunks) uploads at 8.1 MB/s
  and downloads cold at 10.1 MB/s.
- SHA-256 verified on every downloaded object by the harness.

### Large-file uploads on the `bot` backend (flood pacing)

A large object is many ≤16 MB `sendDocument` calls into the **same channel**
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

**Flood pacing makes this survivable** instead of failing it:

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
~20 chunks go near line rate; the tail runs at whatever pace the account's
flood window allows. Downloads are unaffected (many `getFile` pulls do not
hit the per-chat send limit): cold ~10 MB/s, warm CDN up to ~85 MB/s.

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
├── cli.py            # anbarctl — operational CLI (auth/objects/put/get/link…)
├── links.py          # link registry: revoke, live-only listing, dl counters
├── qrcode.py         # dependency-free QR encoder for share links
├── objects.py        # chunking + manifest assembly
├── runtime.py        # runtime-tunable settings (kv-backed, F8)
├── zipper.py         # streaming ZIP (v0.10 bulk download)
├── api/
│   ├── upload.py     # POST /api/v1/upload, /upload/raw
│   ├── ingest.py     # URL ingest: server pulls a remote URL into storage
│   ├── notify.py     # best-effort Telegram ping after ingest
│   ├── download.py   # /f/{id}, links, slugs, pw page, albums, ZIP, stats
│   ├── webauth.py    # session-cookie login for the web dashboard
│   └── admin.py      # status/settings/trash/link manager endpoints
└── storage/
    ├── base.py       # StorageBackend interface + FakeBackend (test contract)
    ├── bot_backend.py# F2: Bot API via httpx (no bot framework)
    └── mtproto_backend.py  # F5: Telethon (dedicated account, 2 GB)
tests/                # 162 passing — API golden tests, CLI round-trip,
                      #   storage contract, hardening
docker/               # Dockerfile (non-root, healthcheck), compose.yaml
nginx/anbar.conf.example
docs/                 # ARCHITECTURE, API, DEPLOY, ROADMAP
.env.example
```

## Quick start (development)

```bash
uv sync --extra dev
uv run pytest -q          # 162 passing
uv run anbarctl version   # anbar 0.10.5
```

Run a local instance with the in-memory backend (no Telegram needed):

```bash
ANBAR_BACKEND=fake ANBAR_BASE_URL=http://127.0.0.1:8567 \
  uv run uvicorn anbar.main:create_app --factory --port 8567
curl http://127.0.0.1:8567/healthz
```

## Deploy (from F2 onward)

**Option A — prebuilt image (GHCR, no build needed):**

```bash
mkdir -p /opt/anbar && cd /opt/anbar
curl -sO https://raw.githubusercontent.com/HA-ir/Anbar/main/.env.example
# edit .env: bot token, base URL, keys
cat > compose.yaml <<'YAML'
services:
  anbar:
    image: ghcr.io/ha-ir/anbar:latest
    env_file: [.env]
    volumes:
      - ./data:/app/data
      - ./secrets:/app/secrets
    ports:
      - "127.0.0.1:8567:8567"   # loopback only — reverse proxy in front
    restart: unless-stopped
YAML
docker compose up -d
curl http://127.0.0.1:8567/healthz
```

**Option B — build from source:**

```bash
git clone https://github.com/HA-ir/Anbar.git && cd Anbar
cp .env.example .env      # bot token, base URL, keys
cd docker && docker compose up -d
curl http://127.0.0.1:8567/healthz
```

Put Caddy or your existing Nginx in front (TLS). See [docs/DEPLOY.md](docs/DEPLOY.md).

## Share links (v0.9.5–v0.10.5)

- **Pretty names** — `POST /f/{id}/link?slug=report-2026` also serves the file
  at `/f/report-2026`. Names are unique (`409` on conflict), `[a-z0-9-_]`,
  max 64 chars, and freed when the object is destroyed.
- **Never-expiring** — `ttl=0` mints a link signed for ~100 years.
- **Passwords** — `&password=…` stores only an HMAC tag; browsers get an RTL
  unlock page (with show/hide eye) whose hidden fields carry `sig`/`exp`
  through the form, so submitting the correct password downloads the file.
  Non-browser clients keep plain HTTP semantics (`401/403`).
- **Download cap** — `&max_dl=N` kills the link after N full downloads.
- **Registry + revoke** — every mint is registered;
  [`GET /api/v1/admin/links`](docs/API.md) lists live links with filename,
  slug, 🔒, ⬇cap and a per-link download counter, and
  `POST /api/v1/admin/links/{obj_id}/revoke/{exp}` kills a link *instantly*
  (its URL starts returning `410 link revoked`).
- **Manage in place** — the ↗ button in the links list opens an in-app modal
  (same look as the share dialog): change TTL / password / download cap →
  the old window is revoked and a fresh link with the same slug is minted,
  ready to copy. The ✕ button revokes outright.

## Shared albums (v0.10.5)

Select multiple files → «اشتراک انتخاب‌شده‌ها» → **one** public link:
`/f/a/<token>` renders an RTL gallery page (no auth needed) with image and
video thumbs, inline audio players, a PDF lightbox and per-file download
links backed by 30-day signatures. Files deleted later just disappear from
the album — the page never breaks. Mint it programmatically via
`POST /f/album {"ids": […], "title": "…"}`.

## Gallery previews (v0.10.4–v0.10.5)

The gallery view plays audio right in each card (native `<audio>` element)
and gives PDFs a proper document card; images/videos keep real thumbnails.
Everything streams straight from Telegram through the server — zero disk
usage for previews (the optional cache stays off by default).

## Trash (v0.10)

`DELETE /f/{id}` no longer destroys anything: it soft-deletes (hides from
listings/downloads, blobs stay in Telegram). Trashed objects:

- appear in `GET /api/v1/admin/trash` with their remaining window;
- come back via `POST /api/v1/admin/trash/{id}/restore`;
- die for real via `DELETE /api/v1/admin/trash/{id}` (or `DELETE /f/{id}?purge=true`)
  which removes the Telegram blobs best-effort and drops metadata;
- purge **automatically after 7 days** (background loop).

The UI adds a trash button (with count badge), restore / delete-forever rows,
and an "empty trash" action.

## Bulk ZIP download (v0.10)

`POST /f/zip` with `{"ids": [...]}` streams one archive built on the fly —
O(one chunk) memory, nothing buffered on disk. Entries keep filenames
(suffixed with the short object id, de-duplicated). Admin/session only,
capped at 100 files / 8 GB per request. The selection bar's «دانلود ZIP»
button drives it from the browser.

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — layers, data flow, chunking, storage locations
- [API reference](docs/API.md) — every endpoint, auth matrix, error codes, **anbarctl CLI reference**
- [Deployment guide](docs/DEPLOY.md) — Docker, Caddy/Nginx, secrets, ops runbook
- [Roadmap](docs/ROADMAP.md) — phase details, decisions, open questions
- [Security policy](SECURITY.md) — how to report vulnerabilities privately
- [Contributing](CONTRIBUTING.md) — dev setup, ground rules, PR guide

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