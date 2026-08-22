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

### `DELETE /f/{id}`  *(F4)*

Removes the remote blob(s) (best-effort `deleteMessage`) + the metadata row.
Owner or admin key. `200` with `{"deleted": true, "id": "…",
"blobs_removed": 1}`, `404` if absent.

```bash
curl -X DELETE https://h/f/k3xQ9aB2mN0p -H "Authorization: Bearer ***"
```

### `POST /f/{id}/link?ttl=3600`  *(F4)*

Mint a signed download link (owner or admin). `ttl` is a query parameter in
seconds (clamped to 60…604800, default 3600). Signature is
`HMAC-SHA256(secret, "<id>:<exp>")`; the secret is the rotated value from
`kv` or `ANBAR_HMAC_SECRET` as fallback.

```json
{"url": "https://h/f/k3xQ9aB2mN0p?sig=59c2…&exp=1787300281",
 "expires_at": 1787300281, "ttl_seconds": 3600}
```

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
| 400 | malformed request (missing name, bad range) |
| 401 | missing/unknown credential |
| 403 | valid credential, not permitted (wrong role, invalid signature) |
| 404 | unknown object id |
| 410 | signed link expired |
| 413 | over configured upload ceiling |
| 429 | rate limited (see `Retry-After`) |
| 502 | upstream (Telegram) failure |
| 503 | service degraded / backend unhealthy |