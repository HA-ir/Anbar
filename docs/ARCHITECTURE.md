# Architecture

## Overview

```
 User (curl / browser / any HTTP client)
   │  POST /api/v1/upload          (auth: API key)
   │  ← { id, url, size, sha256 }
   │  GET /f/{id}  (or signed)     (auth: off by default per-plan → ON)
   │  ← streamed bytes (Range-safe)
   ▼
 ┌────────────────────────────────────────────────────┐
 │                     anbar                          │
 │                                                    │
 │  FastAPI layer                                     │
 │   ├─ api/upload.py     chunking + hash + manifest  │
 │   ├─ api/download.py   manifest walk + Range map   │
 │   └─ api/admin.py      status, auth toggle, list   │
 │                                                    │
 │  auth.py   API keys • HMAC signed URLs • rate limit│
 │  db.py     SQLite (WAL) — objects + kv tables      │
 │  storage/  pluggable backend                       │
 │   ├─ bot_backend.py     Bot API → private channel  │
 │   └─ mtproto_backend.py MTProto → Saved Messages   │
 └────────────────────────────────────────────────────┘
                    │ Bot API / MTProto
                    ▼
          Telegram cloud (files) + Telegram CDN
```

The server **never stores file bytes**. It stores:
1. one SQLite row per object (~100 bytes + manifest),
2. an optional capped LRU cache of hot files (F6, default off).

## Layers

| Layer | Responsibility | Implementation |
|-------|---------------|----------------|
| API | REST surface, validation, streaming | FastAPI + Uvicorn |
| Auth | API keys, signed URLs, toggle, rate limit | HMAC-SHA256 over `id+expiry`; in-DB counters |
| Object layer | chunking, manifests, hashing | `api/upload.py` / `api/download.py` |
| Storage backend | move bytes to/from Telegram | `StorageBackend` interface |
| Metadata | ids, names, sizes, hashes, counters | SQLite WAL |

### Backend interface (the contract)

```python
class StorageBackend(abc.ABC):
    name: str
    max_upload_bytes: int

    async def store(self, data: bytes, name: str) -> ObjectRef
    async def open(self, ref: ObjectRef) -> bytes
    async def delete(self, ref: ObjectRef) -> bool
    async def health(self) -> bool
```

`FakeBackend` (in-memory) implements the same contract and is used by all tests —
CI never touches the network. New backends (S3, local disk) plug in behind the
same seam, so a dead Telegram account does not take the whole service down.

## Data flow

### Upload

```
client bytes ──stream──▶ 16 MB splitter
                            │ per chunk:
                            │   backend.store(chunk) → file_id
                            │   manifest.append({file_id, size})
                            │   (sha256 updated incrementally over the joined stream)
                            ▼
                      SQLite row committed (id, manifest, size, sha256, ...)
                      ← { id, url, size, sha256 }
```

- The upload is **resumable**: partial manifests are durable; a retried upload
  skips chunks whose `file_id` is already recorded (F2 detail).
- Memory is bounded by the chunk size (default 16 MB), not the file size.

### Download

```
GET /f/{id} [Range: bytes=a-b]
  → load row + manifest
  → prefix-sum over chunk sizes → (chunk_index, offset_in_chunk[, ...])
  → for each needed chunk: backend.open(ref) → slice → write to response
  → bump download counter (async, non-blocking)
```

- Multi-chunk ranges are served as one continuous byte stream.
- Responses carry `Content-Type`, `Content-Length`, `Accept-Ranges: bytes`,
  `Content-Disposition: attachment; filename="..."` (RFC 5987 for non-ASCII names).

## Chunking (v1.1)

- `ANBAR_CHUNKING=auto` (default): chunk only when the object exceeds the
  backend ceiling. Single-blob objects keep a one-element manifest — one code path.
- `ANBAR_CHUNK_SIZE_MB=16` default; must stay below the bot ceiling (20 MB).
- Honest trade-off: a 1 GB upload via the bot backend ≈ 64+ API calls →
  expect ~1–5 min/GB due to Telegram flood-wait. Size is no longer a ceiling;
  throughput is bounded by call count.
- MTProto backend: no chunking needed up to 2 GB; the same layer activates above it.

## Where files live in Telegram

| Backend | Location | Notes |
|---------|----------|-------|
| `bot` | **private channel** administered by the bot (zero members) | files posted as documents; `file_id` captured from the message; **messages are never deleted** (deletion = file loss) |
| `mtproto` | **Saved Messages** of a dedicated user account | standard Telethon flow |

Rejected alternatives: groups (visible to members), DM (a bot cannot DM itself),
public channels (security). Each deployment gets its own channel/account, which
keeps instances independent (portability).

## Storage

### SQLite schema

```sql
objects(id TEXT PK, file_id TEXT, backend TEXT, filename TEXT, size INT,
        content_type TEXT, sha256 TEXT, manifest TEXT,
        uploader_key TEXT, created_at INT, downloaded INT)
kv(k TEXT PK, v TEXT)   -- runtime toggles (auth_state), stats
```

WAL mode, `busy_timeout=5000`, single writer (the app). ~1 KB per 1,000 objects.
Scheduled `VACUUM` every 30 days (F6).

### LRU cache (F6, default off)

Capped directory (`ANBAR_CACHE_MAX_MB`), hot objects (download count above a
threshold) are cached; LRU eviction. The cache is never authoritative —
eviction just means the next download re-streams from Telegram.

## Auth model

| Role | Credential | Can |
|------|-----------|-----|
| admin | `ANBAR_ADMIN_KEY` | everything, incl. runtime auth toggle, delete any object |
| uploader | `ANBAR_API_KEY` | upload, delete own objects, mint links |
| public | — | download (with signed link when auth is on) |

Toggle has three levels: env (`ANBAR_AUTH_ENABLED`, needs restart), runtime API
(`POST /api/v1/auth/toggle`, persisted in `kv`), CLI (`anbarctl auth on|off`).

Signed URL format: `{base}/f/{id}?sig=<hmac>&exp=<unix>` (ttl=0 → ~100-year
expiry). Optional extras minted with the link: `slug` (`/f/<name>` pretty
route), `password` (HMAC tag only; browsers get an unlock page whose hidden
fields re-carry `sig`/`exp`), `max_dl` cap, and a per-link download counter
(kv-backed, full GETs only). Every live link is registered in `kv`
(`link:<obj>:<exp>`) so it can be listed and revoked instantly; revoked
windows move to `rev:<obj>:<exp>`. Shared albums store their id list under
`album:<token>` and serve a public gallery at `/f/a/<token>` using 30-day
signatures per item.

## Failure modes

| Failure | Effect | Handling |
|---------|--------|----------|
| Telegram unreachable | uploads/downloads fail | 502/503 + `Retry-After`; metadata intact |
| Flood-wait | request delayed | honor Telegram's `retry_after`, queue internally |
| Account/channel lost (ban) | that backend's files unreadable | backend is swappable via env; remaining backends serve; `/admin/status` flags it |
| HMAC secret leaked | forged links possible | `anbarctl rotate-secret`; expired links die on their own |
| Disk pressure | N/A — only metadata | VACUUM schedule; cache is capped and evictable |