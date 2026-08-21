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