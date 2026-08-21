# tg-link-proxy

Object storage که فایل‌ها را در **تلگرام** نگه می‌دارد و روی سرور شما فقط چند کیلوبایت متادیتا می‌ماند.

- **Upload + Download** دوطرفه با لینک مستقیم
- **فایل روی دیسک سرور نگه نمی‌ماند** — فقط SQLite با متادیتا
- **Auth روشن/خاموش‌شونده** در لحظه (API / CLI / کانفیگ)
- **Chunking** — سقف حجم عملیاً برداشته شده + resumable upload
- **Portable** — Docker-first، deploy روی هر سروری با `docker compose up`

## وضعیت

| Faz | Scope | Status |
|-----|-------|--------|
| F1 | اسکلت: repo، config، DB، API skeleton، Docker، CI | ✅ |
| F2 | Bot backend + upload (multipart + raw) | ⏳ |
| F3 | Streaming download + Range | ⏳ |
| F4 | Auth: API keys، signed URLs، toggle runtime | ⏳ |
| F5 | MTProto backend (تا 2GB، قابل انتخاب) | ⏳ |
| F6 | Hardening: CLI کامل، cache، docs، v1.0 | ⏳ |

## شروع سریع (dev)

```bash
uv sync --extra dev
uv run pytest -q
uv run tglpctl version
```

## Deploy (وقتی F2+ کامل شد)

```bash
cp .env.example .env   # توکن bot و دامنه را ویرایش کن
cd docker && docker compose up -d
# healthz:
curl http://127.0.0.1:8317/healthz
```

Reverse proxy: `nginx/tglink.conf.example` برای Nginx موجود، یا Caddy خودکار.

## ساختار

```
src/tglink/
├── main.py          # app factory
├── config.py        # env-driven settings (pydantic-settings)
├── db.py            # SQLite WAL — متادیتا فقط
├── api/             # upload / download / admin routers
├── storage/         # backend interface + fake (bot: F2, mtproto: F5)
└── cli.py           # tglpctl
```

## فازها و Git

هر فاز = یک branch (`f1-skeleton` ... `f6-hardening`)، commit convention `fN: <what>`،
هر merge به main با tag `v0.N.0`. CI: ruff + pytest + docker smoke.