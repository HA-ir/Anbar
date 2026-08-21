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
| `GET /f/{id}` | open | signed link (or admin) |
| `GET /f/{id}/info` | open | open (metadata only) |
| `DELETE /f/{id}` | uploader key (owner) | uploader key (owner) |
| `POST /api/v1/f/{id}/link` | uploader key | uploader key |
| `GET /api/v1/objects` | admin key | admin key |
| `POST /api/v1/auth/toggle` | admin key | admin key |
| `GET /api/v1/admin/status` | admin key | admin key |
| `GET /healthz` | open | open |

Keys are sent as `Authorization: Bearer <key>`.

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

Removes remote blob(s) + the metadata row. `204` on success, `404` if absent.

### `POST /api/v1/f/{id}/link`  *(F4)*

Mint a signed download link. Body: `{"ttl_seconds": 3600}` (omit for a
permanent link). Returns `{"url": "https://h/f/<id>?e=…&s=…"}`.

### `GET /api/v1/objects`  *(F4)*

List metadata, newest first. Query: `?limit=50&offset=0`.

### `POST /api/v1/auth/toggle`  *(F4)*

Body: `{"enabled": false}` (or `{}` to flip). Persists in `kv`. Returns the new
state. Admin key only.

## Rate limits (F4)

| Scope | Default | Reset |
|-------|---------|-------|
| Download per (IP, id) | 10 req/min | 60 s |
| Upload per API key | 5/min | 60 s |

Exceeding → `429` with `Retry-After`. Counters live in SQLite (no Redis).

## Error model

| Code | Meaning |
|------|---------|
| 400 | malformed request (missing name, bad range) |
| 401 | missing/unknown credential |
| 403 | valid credential, not permitted (wrong role, tampered signature) |
| 404 | unknown object id |
| 410 | signed link expired |
| 413 | over configured upload ceiling |
| 429 | rate limited (see `Retry-After`) |
| 502 | upstream (Telegram) failure |
| 503 | service degraded / backend unhealthy |