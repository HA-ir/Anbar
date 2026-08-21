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
AUTH_ENABLED=true
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
| Rotate HMAC secret | `anbarctl rotate-secret` (F4) |
| List objects | `anbarctl list` (F4) |
| Mint a share link | `anbarctl link /path/file --ttl 3600` (F4) |
| Health | `curl http://127.0.0.1:8317/healthz` |
| Check backend | `anbarctl status` or `/api/v1/admin/status` |
| Update | `git pull && cd docker && docker compose up -d` (DB migrations are forward-only) |

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
- [ ] `AUTH_ENABLED=true` in production
- [ ] admin key ≠ api key, both high-entropy
- [ ] reverse proxy has TLS + HSTS
- [ ] `client_max_body_size` matches your intended ceiling
- [ ] backups of `data/anbar.db` scheduled