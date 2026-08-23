# API Reference

Base path: `/api/v1` for management endpoints; public object links are served at
`/f/{id}` (no version prefix, so they stay short and clean).

All request/response bodies are JSON unless noted. Errors use standard HTTP
status codes with a `{"detail": "..."}` body.

## Auth matrix

| Endpoint | auth off | auth on |
|----------|----------|---------|
| `POST /api/v1/upload` | uploader key | uploader key |
| `POST /api/v1/upload/raw` | uploader key | uploader key |
| `GET /f/{id}` | open | signed link, or admin key |
| `GET /f/{id}/info` | open | open (metadata only) |
| `POST /f/{id}/link?ttl=` | owner or admin key | owner or admin key |
| `DELETE /f/{id}` | owner or admin key | owner or admin key |
| `GET /api/v1/admin/objects` | admin key | admin key |
| `POST /api/v1/admin/auth/toggle` | admin key | admin key |
| `POST /api/v1/admin/auth/rotate-secret` | admin key | admin key |
| `GET /api/v1/admin/status` | admin key | admin key |
| `GET /api/v1/admin/settings` | admin key | admin key |
| `POST /api/v1/admin/settings` | admin key | admin key |
| `POST /api/v1/admin/settings/reset` | admin key | admin key |
| `POST /api/v1/admin/cache/purge` | admin key | admin key |
| `GET /healthz` | open | open |

Keys are sent as `Authorization: Bearer ***`.
`uploader key` = `ANBAR_API_KEY`; `admin key` = `ANBAR_ADMIN_KEY` (strictly
higher privilege). When auth is ON, anonymous calls get `401`; the admin
endpoints additionally reject the plain uploader key with `403`.

## Endpoints

### `GET /healthz`

Liveness probe (Docker/k8s). Returns `200`:
```json
{"status":"ok","service":"anbar","version":"0.1.0"}
```

### `GET /api/v1/admin/status`

```json
{"status":"ok","backend":"bot","auth_enabled":true,"objects":123,"time":1787296681}
```

### `POST /api/v1/upload`  *(F2)*

Multipart form, field `file`. Streams to Telegram in ≤16 MB chunks.

```bash
curl -X POST https://h/api/v1/upload \
  -H "Authorization: Bearer $API_KEY" \
  -F "file=@report.pdf"
```
```json
{"id":"k3xQ9aB2mN0p","url":"https://h/f/k3xQ9aB2mN0p",
 "size":2097152,"sha256":"9f2c…","chunks":1}
```

Errors: `401` bad key · `413` over logical ceiling · `429` rate limited (with `Retry-After`) · `502` Telegram unreachable.

### `POST /api/v1/upload/raw`  *(F2)*

Raw byte stream (no multipart framing) for very large files. Name comes from a
header; size is read from `Content-Length` (or chunked transfer, hashing as it
arrives).

```bash
curl -X POST https://h/api/v1/upload/raw \
  -H "Authorization: Bearer $API_KEY" \
  -H "X-File-Name: disk.img" \
  -H "Content-Length: 3221225472" \
  --data-binary @disk.img
```

Same response shape as multipart upload.

### `GET /f/{id}`  *(F3)*

Streams the object. Honors `Range`.

```bash
curl -OJ https://h/f/k3xQ9aB2mN0p
curl -r 1048576-2097151 https://h/f/k3xQ9aB2mN0p -o chunk.bin
```

Headers: `Content-Type`, `Content-Length`, `Accept-Ranges: bytes`,
`Content-Disposition: attachment; filename="…"`.
`206 Partial Content` for range requests. Errors: `404` unknown id ·
`401/403/410` auth (expired/invalid signature) · `502` Telegram error.

### `GET /f/{id}/info`  *(F3)*

Metadata without the body (open when useful, see matrix).
```json
{"id":"k3xQ9aB2mN0p","filename":"report.pdf","size":2097152,
 "content_type":"application/pdf","sha256":"9f2c…","chunks":1,
 "created_at":1787296681,"downloaded":42}
```

### `DELETE /f/{id}`  *(F4, v0.10 trash)*

**v0.10:** default is a **soft delete** — the object vanishes from listings
and downloads (`404`), but blobs stay in Telegram and the row is restorable
for 7 days. Returns `{"trashed": true, "id": "…", "restore_within_s": 604800}`.

Add `?purge=true` for the old hard delete: remote blob(s) removed
(best-effort `deleteMessage`) + metadata row dropped + pw/cap/slug/link tags
cleaned. Returns `{"purged": true, "id": "…", "blobs_removed": 1}`.
Owner or admin key; purging a trashed object is allowed (idempotent).

```bash
curl -X DELETE https://h/f/k3xQ9aB2mN0p -H "Authorization: Bearer ***"          # → trash
curl -X DELETE "https://h/f/k3xQ9aB2mN0p?purge=true" -H "Authorization: Bearer ***"  # → destroy
```

### `POST /f/{id}/link?ttl=3600`  *(F4, v0.9.5–v0.10.4)*

Mint a signed download link (owner or admin). Query parameters:

| param | default | meaning |
|-------|---------|---------|
| `ttl` | 3600 | validity in seconds (clamped 60…604800; **`0` = never-expiring**, signed ~100 years) |
| `slug` | – | pretty name: object also served at `/f/<name>` (`[a-z0-9-_]`, ≤64 chars, unique; minting your own slug again is idempotent, someone else's → `409`, invalid chars → `400`) |
| `password` | – | link then requires `?pw=<password>`; stored only as an HMAC tag (`HMAC(secret, "pw:<id>:<pw>")[:32]`) — plaintext never persisted |
| `max_dl` | 0 | cap on full downloads through this link (`0` = unlimited); the Nth+1 full GET returns `410 download limit reached` |

Signature is `HMAC-SHA256(secret, "<id>:<exp>")`; the secret is the rotated
value from `kv` or `ANBAR_HMAC_SECRET` as fallback.

```json
{"url": "https://h/f/k3xQ9aB2mN0p?sig=59c2…&exp=1787300281",
 "expires_at": 1787300281, "ttl_seconds": 3600,
 "slug": "report-2026", "pretty_url": "https://h/f/report-2026",
 "password_protected": true, "max_downloads": 5}
```

Every mint is registered in the link registry (see `/api/v1/admin/links`)
and starts a per-link **download counter** (v0.10.4): each *full* GET with
the valid signature bumps that link's count (range/partial requests don't).
The counter is visible via `/api/v1/admin/links` and the in-app manage modal.
Password-protected links serve an RTL unlock page to browsers
(`Accept: text/html`) carrying hidden `sig`/`exp` fields so submitting the
form keeps the signature intact; wrong passwords re-show the page with an
inline error. `GET /f/{id}?view=1` adds `Content-Disposition: inline`
(display instead of download).

### Shared albums — `POST /f/album` + `GET /f/a/{token}`  *(v0.10.5)*

One public link for many objects. Body `{"ids": ["…", …], "title"?: "…"}`
(≤100 ids; missing ids skipped; none valid → `404`). Returns
`{"token", "count", "url": "<base>/f/a/<token>"}`. The album page is a
public RTL gallery (no auth): image/video thumbs, inline audio players,
PDF lightbox, per-file view/download links backed by 30-day signatures.
Objects deleted after sharing are simply hidden from the page; unknown
tokens get a friendly `404`. Admin/session only for minting.

### Link manager page/modal — `GET /api/v1/admin/links/{obj_id}/manage?exp=`  *(v0.10.3)*

Admin/session HTML form showing one link's settings and its download
count. The in-app modal (↗ button in the links list) does the same without
leaving the dashboard: changing TTL / password / download-cap revokes the
current window and mints a fresh link with the same slug; the new URL is
shown with a copy button. Removing both password and cap from a protected
link asks for confirmation first.

### `GET /api/v1/admin/objects?limit=50&offset=0`  *(F4)*

Admin only. Metadata listing, newest first, with `chunks` count; the
`uploader_key` and `manifest` are never exposed.

### `POST /api/v1/admin/auth/toggle`  *(F4)*

Admin only. No body — flips the runtime auth switch (persisted in `kv`),
no restart needed. Returns the new state:

```json
{"auth_enabled": false}
```

`anbarctl auth on|off` is a convenience wrapper that reads current state and
only toggles when needed (idempotent).

### `POST /api/v1/admin/auth/rotate-secret`  *(F4)*

Admin only. Generates a fresh HMAC signing secret; every previously minted
signed link becomes invalid immediately. Returns the new secret so it can be
recorded in your secret store. `anbarctl rotate-secret` wraps this.

### `GET /api/v1/admin/settings`  *(F8)*

Admin only. Returns every tunable setting at its effective value
(env default, or the persisted override if one is set):

```json
{"settings": {"rate_upload": 20, "rate_download": 30, "cache_mb": 512}}
```

### `POST /api/v1/admin/settings`  *(F8)*

Admin only. Body: JSON object of settings to change (subset allowed):

```json
{"rate_upload": 40, "rate_download": 60, "cache_mb": 1024}
```

Values are validated against each setting's range (`0` disables rate
limiters). Takes effect **immediately**, persists across restarts, and no
restart is needed. Returns the changed mapping plus the new effective
settings:

```json
{"changed": {"rate_upload": 40, "rate_download": 60, "cache_mb": 1024},
 "settings": {"rate_upload": 40, "rate_download": 60, "cache_mb": 1024}}
```

> **`cache_mb` + master switch** — a `cache_mb` change re-sizes the LRU
> cache only if `ANBAR_CACHE_ENABLED=true` (env, master switch). When the
> master switch is off the value is stored but inert: no cache directory is
> created and no file ever hits disk. `422` unknown setting / out of range.

### `POST /api/v1/admin/settings/reset`  *(F8)*

Admin only. Body: `{"keys": ["rate_upload", "cache_mb"]}` — drops the
persisted override for each listed key, reverting to the env default.
Omit `keys` (or send `{}`) to reset everything. Returns a per-key flag
(`true` = an override existed and was removed) plus the new effective
settings:

```json
{"reset": {"rate_upload": true, "cache_mb": false},
 "settings": {"rate_upload": 20, "rate_download": 30, "cache_mb": 512}}
```

### `POST /api/v1/admin/cache/purge`  *(F8)*

Admin only. Evicts every cached object from the LRU scratch space (no
metadata change, no data loss). Returns the number of entries removed
(`0` when the cache is disabled):

```json
{"purged": 3}
```

### `GET /api/v1/admin/links?limit=200`  *(v0.10, live-only v0.10.2)*

Registered share links, newest-expiry first. Each row: `obj_id`,
`filename` (null if the object was purged), `exists`, `exp`, `expired`,
`revoked`, mint-time metadata (`slug`, `pw`, `max_dl`, `created_at`) and
the per-link download counter (`downloads`). **Default shows live links
only** — revoked and expired ones are hidden so the list reflects what is
actually shareable right now; pass `?include_dead=1` for the audit view.

### `POST /api/v1/admin/links/{obj_id}/revoke/{exp}`  *(v0.10)*

Kill one link **immediately**: its URL keeps the signature but starts
returning `410 link revoked`. `200 {"revoked": true, …}`; `404` when the
link was already revoked or never registered. When an object's last live
link goes, its pw / download-cap / slug tags are dropped too.

### `GET /api/v1/admin/objects/{id}/link-info`  *(v0.10)*

The same rows filtered to one object (used by the file-detail modal).

### `GET /api/v1/admin/trash`  *(v0.10)*

Soft-deleted objects: `items[]` with `deleted_at` and `purge_in_s` (seconds
until the automatic hard delete), plus `count`.

### `POST /api/v1/admin/trash/{id}/restore`  *(v0.10)*

Bring a trashed object back (`200 {"restored": id}`; `404` if not in trash).

### `DELETE /api/v1/admin/trash/{id}`  *(v0.10)*

Destroy one trashed object right now (blobs + metadata + tags).
`200 {"purged": id, "blobs_removed": N}`. Admin only.

### `POST /f/zip`  *(v0.10)*

Stream a ZIP of several objects. Body `{"ids": ["…", …]}` (≤100 ids, ≤8 GB
total). The archive is generated on the fly (O(chunk) memory, nothing
buffered on disk); entries keep filenames with a short-id suffix and are
de-duplicated. Admin/session only; `application/zip` attachment named
`anbar-YYYYMMDD-HHMMSS.zip`. Missing ids are skipped; all-missing → `404`.

## `anbarctl` — the CLI  *(F4, v0.10.5)*

`anbarctl` ships with the package (`[project.scripts]` in pyproject.toml)
and talks to a running server over plain HTTP — no DB access needed, so it
works remotely too. Config via flags or env:

| source | flag | env |
|--------|------|-----|
| Server URL | `--base-url` | `ANBAR_BASE_URL` (default `http://127.0.0.1:8317`) |
| Admin key | `--admin-key` | `ANBAR_ADMIN_KEY` |

Commands (all verified against a live v0.10.5 instance):

| command | what it does |
|---------|--------------|
| `anbarctl version` | print client version (no server needed) |
| `anbarctl auth on\|off` | runtime toggle; idempotent ("already ON/OFF") |
| `anbarctl rotate-secret` | rotate HMAC secret (all old signed links die) |
| `anbarctl objects [--limit N]` | list objects, newest first |
| `anbarctl link <id> [--ttl S]` | mint a signed link (default 3600s), prints URL |
| `anbarctl put <file>` | multipart upload; prints `uploaded <id> (<bytes>)` |
| `anbarctl get <id> -o <out>` | mint a 120 s link and stream the file to `<out>` |
| `anbarctl login --api-id … --api-hash … --phone …` | MTProto session bootstrap |
| `anbarctl install [--env-file F]` | write a systemd unit (non-root user) |

Example round-trip:

```bash
export ANBAR_BASE_URL=https://anbar.example.com ANBAR_ADMIN_KEY=***
anbarctl put report.pdf          # → uploaded k3xQ9aB2mN0p (482113 bytes)
anbarctl link k3xQ9aB2mN0p       # → https://anbar.example.com/f/k3xQ…?sig=…
anbarctl get k3xQ9aB2mN0p -o copy.pdf
```

Notes:

- `put/get` are streaming-friendly but read the whole file into memory for
  the multipart body — fine for typical files, not for multi-GB uploads.
- Behind Cloudflare, some datacenter IPs get `403` from CF's bot rules on
  python-urllib user agents; run the CLI from the host itself (the loopback
  bind, e.g. `http://127.0.0.1:8317`) or allowlist your IP in that case.
- Exit codes: `0` success, `1` HTTP/business error (message on stderr),
  `2` cannot reach the server.

## Rate limits

Fixed-window counters in SQLite (no Redis):

- **Downloads** — limited per `(client IP, object id)` to
  `ANBAR_RATE_DOWNLOAD_PER_MIN` requests/minute (default 30).
- **Uploads** — limited per API key to `ANBAR_RATE_UPLOAD_PER_MIN`
  requests/minute (default 20).

A `0` limit disables that limiter. Over-limit requests return
`429` with a `Retry-After` header (seconds until the window resets).

## Error model

| Code | Meaning |
|------|---------|
| 400 | malformed request (missing name, bad range, invalid slug) |
| 401 | missing/unknown credential |
| 403 | valid credential, not permitted (wrong role, invalid signature) |
| 404 | unknown object id |
| 409 | slug already taken by another object *(v0.9.5)* |
| 410 | signed link expired — or **revoked** (`link revoked`) *(v0.10)* |
| 413 | over configured upload ceiling / ZIP selection too large |
| 429 | rate limited (see `Retry-After`) |
| 502 | upstream (Telegram) failure |
| 503 | service degraded / backend unhealthy |