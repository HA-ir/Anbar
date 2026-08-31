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
- [x] login screen — L9 (keyInput type=password + eye toggle، err فقط متن ترجمه‌شده، کلید بعد از verify در localStorage، پاک‌سازی on-boot اگر /ui/me نشد: سالم)
- [~] file list + rendering — L9 (esc() روی همه اسم‌ها/titles، id ها در attr های ساده، data-id ها از API داخلی: سالم)
- [~] upload flow (multiple/chunk/resume) — L9 (X-Upload-Id/X-Resume-From، progress کل فایل، ZK encrypt قبل ارسال، retry per-item: سالم)
- [~] folder nav + breadcrumbs — L9 (popstate+pushState هماهنگ، breadcrumb esc، create/rename/copy پاک‌سازی کاراکترهای مسیر: سالم)
- [~] settings/theme (dark-light، دو زبانه) — L9 (setLang با fade+گارد دابل‌کلیک، data-i18n کامل، theme از prefers-color-scheme: سالم)
- [x] MTProto login drawer — L9 (single-init گارد سر جایش، فیلدهای توکن/hash هرگز prefetch نمی‌شوند — B-054/B-055 پایدار: سالم)
- [~] ZIP/export flow — L9 (فیلتر folder: ids، cap سمت سرور 8GB، Authorization header هنگام _apiKey: سالم)
- [~] modals (rename/delete/link/info) — L9 (esc در همه innerHTMLها، guardBtn روی دکمه‌های اصلی، confirm قبل از destructive ها: سالم)
- [~] admin dashboard (stats، storage legend، settings) — L9 (audit logs esc، backup download/import با header، telegram-config masked: سالم)
- [~] JS توابع کمکی (esc، fetch wrapper، toast) — L9 (esc=textContent/innerHTML، toast esc می‌کند، copyText fallback execCommand: سالم)

### miniapp.html
- [x] renderList + esc — L5 (B-050 XSS، فیکس شد)
- [x] باقی فایل (init/TG theme، upload widget، search/filter، copyLink) — L7 سالم (auth via initData، بدون کلید در کد)

- [~] icon.svg / manifest.webmanifest — استاتیک، L3

## 5. امنیت — endpoint به endpoint (docs/API.md)

- [~] POST /api/v1/upload (+raw) — L1
- [~] GET /f/{id} — L1 (B-041) + L4 (B-049 آلبوم)
- [~] GET /f/{id}/info — L8 (فقط metadata، بدون manifest/uploader_key — تست pin شد)
- [~] POST /f/{id}/link (ttl، max_dl، پسورد) — L8 (HMAC زمان-ثابت، pw tag هرگز plaintext، ttl clamp سالم)
- [~] DELETE /f/{id} (trash/purge) — L8 (owner/admin چک، kv tags پاک، tombstone شرطی)
- [~] /api/v1/admin/* (objects، auth toggle/rotate، status، settings، cache purge) — L1
- [~] /healthz — L3
- [~] S3 API (PUT/GET/DELETE object) — L8 (traversal sweep: 404/405 تمیز، keys opaque kv؛ Range از L2)
- [~] webauth/2FA flow — L8 (کوکی duplicate-tolerant، همه مسیرهای خراب بدون 500)
- [x] header injection / path traversal sweep سراسری — L8 (CRLF filename سندباکس شد، sweep تست pin)
- [~] secret leakage در لاگ‌ها — L8 (guard تست استاتیک: log_audit/print هرگز secret نمی‌فرستد)

## 6. زیرساخت

- [~] docker/Dockerfile — L9 (non-root، healthcheck، pip install بدونextras: سالم)
- [~] docker/compose.yaml — L9 (loopback-only port، no-new-privileges، env_file: سالم)
- [x] .dockerignore — L9 (B-058 فیکس: secrets/heavy dirs از build context خارج شدند)
- [~] .github/workflows/ci.yaml — L9 (lint+test، docker build+healthz smoke: سالم)
- [~] .github/workflows/security.yaml — L9 (pip-audit weekly، --strict: سالم)
- [~] .github/workflows/publish.yaml — L9 (GHCR با GITHUB_TOKEN، trivy scan gate HIGH/CRITICAL: سالم)
- [x] scripts/recover.py — L9 (B-057 path traversal، فیکس + تست)
- [~] scripts/bench*.py (۴ فایل) — L9 (کلیدها از .env خوانده می‌شوند، هرگز print/log نمی‌شوند: سالم)

## 7. تست‌ها — پوشش هر ماژول

- [x] gap-analysis — L9: تست مستقیم نداشتند: ratelimit.py، qrcode.py، scripts/recover.py، main.py (فقط غیرمستقیم) · ratelimit و qrcode و recover در L9 تست مستقیم گرفتند (test_v01519_audit.py، ۲۴۳→۲۶۰) · main.py/lifespan پوشش غیرمستقیم کامل در e2e — بدون تست مستقیم باقی می‌ماند (پذیرفته‌شده)

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
