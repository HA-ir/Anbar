# Deployment Guide

Anbar is Docker-first and server-agnostic. The same image runs on a $5 VPS, a
home server, or inside a k8s namespace. Nothing is specific to any one host.

## Prerequisites

- Docker + Docker Compose v2
- a reverse proxy that terminates TLS (Caddy recommended, or existing Nginx)
- a Telegram bot token (BotFather) and, for the `bot` backend, a **private
  channel** the bot administers (see "Creating the channel")
- (only for `mtproto`) a dedicated Telegram account + `api_id`/`api_hash` from
  my.telegram.org

## 1. Configure

```bash
cp .env.example .env
```

Minimum for a `bot` backend:

```env
ANBAR_BASE_URL=https://d.example.com
ANBAR_BACKEND=bot
ANBAR_BOT_TOKEN=123456:ABC-DEF...
ANBAR_ADMIN_KEY=<32+ random chars>
ANBAR_API_KEY=<32+ random chars>
ANBAR_HMAC_SECRET=<32+ random chars>
ANBAR_CHANNEL_ID=@yourprivatechannel     # F2: where files are posted
ANBAR_AUTH_ENABLED=true
ANBAR_RATE_DOWNLOAD_PER_MIN=30           # F6: per (IP, object); 0 disables
ANBAR_RATE_UPLOAD_PER_MIN=20             # F6: per API key; 0 disables
ANBAR_CACHE_ENABLED=false                # F6: optional LRU cache (default off)
ANBAR_CACHE_MAX_MB=512
```

Generate secrets:
```bash
head -c 32 /dev/urandom | base64
```

> Never commit `.env`. Only `.env.example` (placeholders) is tracked.

### Creating the channel (one time, ~2 min)

1. In Telegram, `@BotFather` → `/newbot` → get the **token**.
2. New Channel → name it (e.g. `anbar storage`) → keep it **Private**.
3. Channel → Members → **Add Admins** → select the bot → grant **Full rights**.
4. Copy the channel's `@username` (or numeric id) into `ANBAR_CHANNEL_ID`.

The bot cannot create channels via the Bot API, so this step is manual.

### MTProto backend (F5 — files up to 2 GB)

`ANBAR_BACKEND=mtproto` uses a dedicated **user account** (Telethon) instead of
a bot. Blobs live in the account's Saved Messages.

1. Get `api_id` / `api_hash` from https://my.telegram.org (→ *API development
   tools*). Use a **dedicated account** — not your personal one.
2. Log in once (interactive, ~1 min; needs a TTY so Telethon can ask for the
   login code and any 2FA password):

   ```bash
   docker compose run --rm anbar anbarctl login \
     --api-id 123456 --api-hash abcdef --phone +98...
   ```

   This writes `./secrets/session.session` (already a mounted volume).
3. Configure:

   ```env
   ANBAR_BACKEND=mtproto
   ANBAR_API_ID=123456
   ANBAR_API_HASH=abcdef...
   ANBAR_SESSION_FILE=/app/secrets/session.session
   # chunk size may now be raised: 49 MB is the default cap
   ANBAR_CHUNK_SIZE_MB=49
   ```
4. `docker compose up -d`. On startup the server loads the session file — it
   never authenticates itself, so no phone number or code is ever in `.env`.

Notes:

- **Keep the session file** (`./secrets/`): losing it strands all mtproto
  objects and requires re-login.
- The account will show as *online* in Telegram while the server runs —
  cosmetic, but expected for a storage account.
- Bot (20 MB) and MTProto (2 GB) objects **coexist**: each object row records
  which backend stored it (see "Upgrading backends" below).

## 2. Run

```bash
cd docker
docker compose up -d
docker compose logs -f anbar
curl http://127.0.0.1:8317/healthz
```

The service binds to **127.0.0.1:8317** only — expose it solely through the
reverse proxy.

### Volumes

| Mount | Content |
|-------|---------|
| `./data` | `anbar.db` (metadata) + capped cache |
| `./secrets` | MTProto session (optional, F5) + rotated HMAC secret |

Back up `./data/anbar.db` periodically (a few MB). Backing up the DB does **not**
restore file bytes — those live in Telegram; the DB only points at them.

> **Ownership pitfall:** the container runs as the non-root `anbar` user
> (UID 999). Host directories bind-mounted to `/app/data` and `/app/secrets`
> must be writable by UID 999, otherwise startup fails with
> `sqlite3.OperationalError: unable to open database file`. Fix once:
> `sudo chown -R 999:999 ./data ./secrets` (or create a local `anbar` user with
> UID 999 and chown to it). Never use `chmod 777` in production.

## 3. Reverse proxy

### Caddy (automatic HTTPS)

```
d.example.com {
    reverse_proxy 127.0.0.1:8317
}
```

### Nginx (existing host)

Copy `nginx/anbar.conf.example` into your sites dir. Key directives:

```nginx
server {
    listen 443 ssl http2;
    server_name d.example.com;

    client_max_body_size 2g;          # allow large uploads
    proxy_request_buffering off;       # stream uploads to app, don't buffer
    client_body_buffer_size 128k;

    location / {
        proxy_pass http://127.0.0.1:8317;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;           # stream downloads back
        proxy_read_timeout 600s;       # long-lived large transfers
    }
}
```

## 4. Verify (golden test)

```bash
# upload
curl -s -X POST https://d.example.com/api/v1/upload \
  -H "Authorization: Bearer $ANBAR_API_KEY" -F "file=@sample.iso"
# → {"id":"…","url":"https://d.example.com/f/…","sha256":"…"}

# download + verify
curl -sOJ "https://d.example.com/f/<id>"
sha256sum <downloaded>        # must match the reported sha256
```

Confirm the server's local disk did **not** grow by the file size (only a few
KB of metadata). That is the whole point of Anbar.

## Operations runbook

| Task | Command |
|------|---------|
| Toggle auth (no restart) | `anbarctl auth on` / `anbarctl auth off` |
| Rotate HMAC secret | `anbarctl rotate-secret` |
| List objects | `anbarctl objects [--limit 50]` |
| Mint a share link | `anbarctl link <object_id> --ttl 3600` |
| Upload a file | `anbarctl put /path/file` → prints object id |
| Download an object | `anbarctl get <id> -o out.bin` (mints a 120 s link) |
| Revoke one link | `curl -X POST …/api/v1/admin/links/<obj>/revoke/<exp>` (admin key) |
| List live links + counters | `curl …/api/v1/admin/links?limit=200` (admin key) |
| MTProto login (once) | `anbarctl login --api-id … --api-hash … --phone …` |
| Health | `curl http://127.0.0.1:8317/healthz` |
| Check backend / cache | `curl …/api/v1/admin/status` (admin key) |
| Install as systemd (no Docker) | `anbarctl install --env-file /etc/anbar/.env` (then `systemctl enable --now anbar`) |
| Update | `git pull && cd docker && docker compose up -d` (DB migrations are forward-only) |

CLI config: `--base-url` / `$ANBAR_BASE_URL`, `--admin-key` /
`$ANBAR_ADMIN_KEY`. On the server itself use
`ANBAR_BASE_URL=http://127.0.0.1:8317` — going through Cloudflare with the
python-urllib user agent can trip CF bot rules (`403`). Full command
reference lives in [API.md](API.md#anbarctl--the-cli-f4-v0105).

### Non-Docker (fallback)

`anbarctl install` writes a systemd unit (non-root user `anbar`, `EnvironmentFile`
pointing at `.env`). For hosts without Docker.

## Upgrading backends / migration

Backends are selected via `ANBAR_BACKEND`. Because every object row records the
backend that stored it, you can run **mixed** stores: switch the default for new
uploads without touching objects that live on another backend. A lost backend
only makes its own objects unreadable; the rest keep serving.

## Security checklist

- [ ] `.env` is `chmod 600`, not in git
- [ ] service reachable only via reverse proxy (loopback bind)
- [ ] `ANBAR_AUTH_ENABLED=true` in production
- [ ] admin key ≠ api key, both high-entropy
- [ ] reverse proxy has TLS + HSTS
- [ ] `client_max_body_size` matches your intended ceiling
- [ ] backups of `data/anbar.db` scheduled