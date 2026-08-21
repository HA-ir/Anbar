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

## Rate limits *(F6)*

Not implemented in F4 — planned for the hardening phase (per-IP download and
per-key upload counters in SQLite, `429` + `Retry-After`).

## Error model

| Code | Meaning |
|------|---------|
| 400 | malformed request (missing name, bad range) |
| 401 | missing/unknown credential |
| 403 | valid credential, not permitted (wrong role, invalid signature) |
| 404 | unknown object id |
| 410 | signed link expired |
| 413 | over configured upload ceiling |
| 429 | rate limited (see `Retry-After`) — F6 |
| 502 | upstream (Telegram) failure |
| 503 | service degraded / backend unhealthy |