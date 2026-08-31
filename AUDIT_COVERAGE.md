# Anbar — Audit Coverage Map (نقشه پوشش ممیزی)

> نگهداری: وضعیت هر فایل پس از ممیزی آپدیت می‌شود — پاک نشود.
> وضعیت‌ها: `[ ]` بررسی‌نشده · `[~]` بررسی‌شده سالم · `[x]` بررسی‌شده + فیکس · `[!]` مشکل یافت/فیکس نشده
> حلقه‌ها: L1=v0.15.12 · L2=v0.15.13 · L4=v0.15.14 · L5=v0.15.15 · L6=v0.15.16 · L7=v0.15.17 · L8=v0.15.18 · L9=v0.15.19 (پوشش کامل) · **L10 باز شد**

## 1. Backend — ریشه (src/anbar/*.py)

- [ ] auth.py
- [ ] cache.py
- [ ] cli.py
- [ ] config.py
- [ ] crypto.py
- [ ] db.py
- [ ] links.py
- [ ] main.py
- [ ] objects.py
- [ ] qrcode.py
- [ ] ratelimit.py
- [ ] runtime.py
- [ ] self_healing.py
- [ ] webauth.py
- [ ] zipper.py

## 2. Backend — API (src/anbar/api/*.py)

- [ ] admin.py
- [ ] download.py
- [ ] ingest.py
- [ ] notify.py
- [ ] s3.py
- [ ] upload.py
- [ ] web.py

## 3. Backend — Storage (src/anbar/storage/*.py)

- [ ] base.py
- [ ] bot_backend.py
- [ ] bot_harvester.py
- [ ] bot_pool.py
- [ ] mtproto_backend.py

## 4. UI/UX (src/anbar/ui/)

### index.html (قطعات منطقی)
- [ ] login screen
- [ ] file list + rendering
- [ ] upload flow (multiple/chunk/resume)
- [ ] folder nav + breadcrumbs
- [ ] settings/theme (dark-light، دو زبانه)
- [ ] MTProto login drawer
- [ ] ZIP/export flow
- [ ] modals (rename/delete/link/info)
- [ ] admin dashboard (stats، storage legend، settings)
- [ ] JS توابع کمکی (esc، fetch wrapper، toast)

### miniapp.html
- [ ] renderList + esc
- [ ] باقی فایل (init/TG theme، upload widget، search/filter، copyLink)

- [ ] icon.svg / manifest.webmanifest

## 5. امنیت — endpoint به endpoint (docs/API.md)

- [ ] POST /api/v1/upload (+raw)
- [ ] GET /f/{id}
- [ ] GET /f/{id}/info
- [ ] POST /f/{id}/link (ttl، max_dl، پسورد)
- [ ] DELETE /f/{id} (trash/purge)
- [ ] /api/v1/admin/* (objects، auth toggle/rotate، status، settings، cache purge)
- [ ] /healthz
- [ ] S3 API (PUT/GET/DELETE object)
- [ ] webauth/2FA flow
- [ ] header injection / path traversal sweep سراسری
- [ ] secret leakage در لاگ‌ها

## 6. زیرساخت

- [ ] docker/Dockerfile
- [ ] docker/compose.yaml
- [ ] .dockerignore
- [ ] .github/workflows/ci.yaml
- [ ] .github/workflows/security.yaml
- [ ] .github/workflows/publish.yaml
- [ ] scripts/recover.py
- [ ] scripts/bench*.py (۴ فایل)

## 7. تست‌ها — پوشش هر ماژول

- [ ] gap-analysis

## 8. سابقه حلقه‌ها

| Loop | یافته‌ها | پوشش اضافه‌شده |
|---|---|---|
| L1 | B-041…B-046 | auth، webauth، ratelimit، zipper، qrcode، links، download، upload، admin |
| L2 | B-047، B-048 | s3، db، objects |
| L3 | — | بازرسی وضعیت |
| L4 | B-049 | آلبوم گالری |
| L5 | B-050 | miniapp renderList، bot_*، mtproto، ingest، cli، notify |
| L6 | B-051…B-053 | cache، config، crypto، main، runtime، self_healing، storage/base، api/web |
| L7 | B-054…B-056 | admin.py کامل، miniapp.html کامل، داشبورد settings |
| L8 | — | GET info، POST link، DELETE، S3، webauth/2FA، sweep سراسری، nginx |
| L9 | B-057، B-058 | index.html کامل (۱۰ قطعه)، Dockerfile/compose/.dockerignore، ۳ workflow، bench×۴، recover.py، gap-analysis تست‌ها — **پوشش ۱۰۰٪** |
