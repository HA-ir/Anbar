# Anbar — Audit Coverage Map (نقشه پوشش ممیزی)

> نگهداری: وضعیت هر فایل پس از ممیزی آپدیت می‌شود — پاک نشود.
> وضعیت‌ها: `[ ]` بررسی‌نشده · `[~]` بررسی‌شده سالم · `[x]` بررسی‌شده + فیکس · `[!]` مشکل یافت/فیکس نشده
> حلقه‌ها: L1=v0.15.12 · L2=v0.15.13 · L4=v0.15.14 · L5=v0.15.15

## 1. Backend — ریشه (src/anbar/*.py)

- [~] auth.py — L1 (B-042 nosniff + تست)
- [x] cache.py — L6 (B-051 نشتی temp فایل، فیکس + ۳ تست)
- [~] cli.py — L5 (بدون subprocess/eval)
- [~] config.py — L6 (validators، bot_tokens dedupe، chunk cap: سالم)
- [~] crypto.py — L6 (AES-256-GCM ctypes، client ZK PBKDF2: سالم)
- [~] db.py — L2 (ممیزی همراه B-047)
- [~] links.py — L1
- [x] main.py — L6 (B-053 حلقه prune می‌مرد، فیکس؛ بقیه lifespan/backup سالم)
- [~] objects.py — L2
- [~] qrcode.py — L1
- [~] ratelimit.py — L1
- [~] runtime.py — L6 (SPEC validation، bool guard: سالم)
- [~] self_healing.py — L6 (سالم)
- [~] webauth.py — L1
- [~] zipper.py — L1

## 2. Backend — API (src/anbar/api/*.py)

- [x] admin.py — L1 + L7 کامل (B-054 نشت توکن/api_hash در telegram-config، فیکس؛ B-055 corrupt .env → 500، فیکس؛ بقیه endpointها سالم)
- [~] download.py — L1 (B-041 فارسی filename → 500، فیکس شد)؛ مسیر cache-fill خودش پاک‌سازی می‌کند (L6)
- [~] ingest.py — L5 (URL pull سالم)
- [~] notify.py — L5 (best-effort)
- [x] s3.py — L2 (B-047 Range → 416)
- [~] upload.py — L1
- [x] web.py — L6 (B-052 login 500 با JSON غیر-dict، فیکس + ۳ تست؛ cookie flags/logout سالم)

## 3. Backend — Storage (src/anbar/storage/*.py)

- [~] base.py — L6 (ObjectRef/StorageBackend ABC: سالم)
- [~] bot_backend.py — L5 (paced send, flood budget, CDN retry)
- [~] bot_harvester.py — L5 (offset persistence)
- [~] bot_pool.py — L5 (round-robin)
- [~] mtproto_backend.py — L5 (parallel parts, dead-link heal)

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
- [x] renderList + esc — L5 (B-050 XSS، فیکس شد)
- [x] باقی فایل (init/TG theme، upload widget، search/filter، copyLink) — L7 سالم (auth via initData، بدون کلید در کد)

- [~] icon.svg / manifest.webmanifest — استاتیک، L3

## 5. امنیت — endpoint به endpoint (docs/API.md)

- [~] POST /api/v1/upload (+raw) — L1
- [~] GET /f/{id} — L1 (B-041) + L4 (B-049 آلبوم)
- [ ] GET /f/{id}/info
- [ ] POST /f/{id}/link (ttl، max_dl، پسورد)
- [ ] DELETE /f/{id} (trash/purge)
- [~] /api/v1/admin/* (objects، auth toggle/rotate، status، settings، cache purge) — L1
- [~] /healthz — L3
- [ ] S3 API (PUT/GET/DELETE object) — L2 فقط Range
- [ ] webauth/2FA flow
- [ ] header injection / path traversal sweep سراسری
- [ ] secret leakage در لاگ‌ها

## 6. زیرساخت

- [ ] docker/Dockerfile
- [ ] docker/compose.yaml
- [ ] nginx/anbar.conf.example
- [ ] .github/workflows/ci.yaml
- [ ] .github/workflows/security.yaml
- [ ] .github/workflows/publish.yaml
- [ ] scripts/recover.py
- [ ] scripts/bench*.py (۴ فایل)

## 7. تست‌ها — پوشش هر ماژول

- [ ] gap-analysis: کدام ماژول تست ندارد/ناقص است (پس از تکمیل بندهای ۱–۳)

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
