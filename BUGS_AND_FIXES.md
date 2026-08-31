# Anbar — Bugs & Fixes (Cumulative)

> فایل تجمیعی باگ‌ها و فیکس‌ها. آخرین به‌روزرسانی: 2026-08-31 — نسخه v0.15.16

## خلاصه Audit Loops (دور به دور)

| Loop | نسخه | یافته‌ها | نتیجه |
|---|---|---|---|
| #1 | v0.15.12 | B-041 (download 500 با نام فارسی، HIGH)، B-042 (nosniff)، B-043 (نشتی کلاینت Telethon)، B-044–B-046 (UI) | ۶ فیکس + ۶ تست — پوشش: auth.py، webauth، ratelimit، zipper، qrcode، links، download، upload، admin |
| #2 | v0.15.13 | B-047 (S3 Range خراب → 500، MED)، B-048 (لجند «Other»، TRIVIAL) | ۲ فیکس + ۵ تست — پوشش: s3.py، db.py، objects.py |
| #3 | — | بازرسی وضعیت (git sync، ruff، 220 تست، prod health، TODO/console.log) | بدون باگ جدید |
| #4 | v0.15.14 | B-049 (Stored XSS گالری آلبوم، HIGH) | ۱ فیکس + ۳ تست |
| #5 | v0.15.15 | B-050 (XSS لیست فایل Mini App، HIGH) | ۱ فیکس + ۲ تست — پوشش: bot_backend/pool/harvester، mtproto_backend، ingest، cli، notify |
| #6 | v0.15.16 | B-051 (نشتی فایل temp در DiskLRU، MED)، B-052 (login 500 با JSON غیر-object، LOW)، B-053 (مرگ حلقه prune روی خطای گذرا، LOW) | ۳ فیکس + ۶ تست — ساخت AUDIT_COVERAGE.md؛ پوشش: cache، config، crypto، main، runtime، self_healing، storage/base، api/web |

**جمع:** ۱۳ باگ (B-041…B-053) · تست‌ها 209 → 231 · سطح‌ها: 3×HIGH، 4×MEDIUM، 4×LOW، 2×TRIVIAL
**درس تکرارشونده:** الگوی «innerHTML بدون escape با داده کاربر» دو بار (آلبوم + miniapp) — بعد از این، همه render pathهای جدید باید esc/escape دارند.
**CI:** یک خطای E501 (خط طولانی) هم پس از loop #1 گرفته و فیکس شد.

## v0.15.16 — 2026-08-31 (Audit Fixes — Loop #6)

### B-051 · نشتی فایل temp در DiskLRU cache — Severity: MEDIUM
- **باس:** `DiskLRU.add()` در دو مسیر فایل temp را بدون unlink رها می‌کرد: (۱) آبجکت بزرگ‌تر از کل بودجه → فایل پرشده caller یتیم روی دیسک؛ (۲) add دوباره با همان `obj_id` (مثلاً دو دانلود کامل همزمان یک آبجکت) → entry قبلی pop می‌شد ولی فایلش unlink نمی‌شد و `_bytes` هم دوبار حساب می‌شد. در طول عمر پروسه فایل‌های یتیم volume اphemeral را پر می‌کردند. مسیر پر کردن (filling_stream در download.py) خودش در خطا/abort پاک می‌کرد — فقط مسیرهای add مقصر بودند.
- **فیکس:** `add()` همیشه فایل reject/replace شده را unlink می‌کند، حساب `_bytes` را دقیق نگه می‌دارد و bool موفقیت برمی‌گرداند.
- **تست:** ۳ تست جدید در `test_cache_leak.py` (replace-unlink، reject-unlink، evict-unlink).

### B-052 · `/ui/login` با JSON غیر-object → HTTP 500 — Severity: LOW
- **باس:** `body = await request.json()` بدون چک نوع؛ body مثل `[1,2,3]` یا `"x"` یا `42` باعث `AttributeError` روی `.get()` و 500 می‌شد.
- **فیکس:** هر JSON غیر-dict → همان 400 استاندارد `expected JSON {key}`.
- **تست:** ۳ تست در `test_web_login_body.py`.

### B-053 · مرگ دائمی حلقه prune پنجره‌های rate روی خطای گذرا — Severity: LOW
- **باس:** `_prune_rate_loop` در `main.py` روی هر Exception `return` می‌کرد — یک خطای گذرای db (مثل SQLite busy) حلقه را برای همیشه می‌کشت و جدول `rate_windows` بی‌کران رشد می‌کرد.
- **فیکس:** خطاها فقط log-و-continue؛ خروج فقط با CancelledError (shutdown).
- **تست:** رفتار حلقه پایدار — پوشش غیرمستقیم با سوئیت موجود.

### نکات audit شده در این دور (بدون باگ)
- `config.py` (validators، bot_tokens dedupe، chunk cap): سالم.
- `crypto.py` (AES-256-GCM via ctypes، client ZK PBKDF2 100k): سالم — طول nonce/tag استاندارد.
- `runtime.py` (SPEC validation، bool guard در set_int): سالم.
- `self_healing.py`، `storage/base.py`: سالم.
- `api/web.py` بقیه (cookie flags: HttpOnly/SameSite=Lax/Secure-on-https، logout فقط کوکی): سالم.
- `main.py` بقیه (lifespan، auto-backup loop، backend wiring): سالم.

## v0.15.15 — 2026-08-31 (Audit Fixes — Loop #5)

### B-050 · XSS در لیست فایل‌های Mini App تلگرام — Severity: HIGH
- **باس:** `renderList()` در `miniapp.html` نام فایل‌ها را بدون escape داخل template literal به `innerHTML` می‌داد — نام فایل مخرب (`<img src=x onerror=...>`) داخل webview تلگرام اجرا می‌شد. (الگوی مشابه B-049 در صفحه آلبوم.)
- **فیکس:** helper `esc()` (textContent→innerHTML) برای filename و id داخل onclick + `encodeURIComponent` روی id لینک دانلود.
- **تست:** ۲ تست ساختاری در `test_miniapp_xss.py`.

### نکات audit شده در این دور (بدون باگ)
- `bot_backend.py` (paced send, flood budget, CDN retry با backoff): منطق سالم.
- `bot_pool.py` (round-robin), `bot_harvester.py` (offset persistence): سالم.
- `mtproto_backend.py` (parallel upload parts, dead-link heal): سالم.
- `ingest.py` (URL pull: http(s)-only, size ceiling, concurrency semaphore, idle timeout): سالم.
- `cli.py` (login/put/get/crypto/s3): سالم — بدون subprocess/eval.
- `notify.py`: best-effort، خطاها job را نمی‌شکنند: سالم.

## v0.15.14 — 2026-08-31 (Audit Fixes — Loop #4)

### B-049 · Stored XSS در صفحه گالری آلبوم (`/f/a/<token>`) — Severity: HIGH
- **باس:** در صفحه عمومی آلبوم، نام فایل‌ها از JSON payload مستقیم داخل `innerHTML` تزریق می‌شد بدون escape. نام فایل ورودی دلخواه uploader است — `<img src=x onerror=alert(1)>.png` به‌عنوان stored XSS روی صفحه اشتراک عمومی اجرا می‌شد. (عنوان آلبوم escape می‌شد ولی نام‌ها نه.)
- **فیکس:** Escape سمت سرور نام همه آیتم‌ها و عنوان قبل از embed شدن payload در HTML.
- **تست:** ۳ تست جدید در `test_album_xss.py` (malicious filename / normal filename / title escape).

## v0.15.13 — 2026-08-31 (Audit Fixes — Loop #2)

### B-047 · S3 GetObject با Range خراب → HTTP 500 — Severity: MEDIUM
- **باس:** پارس `Range` در `s3.py` بدون هیچ گاردی بود: `bytes=abc-def` (ValueError)، `bytes=5-2` (بازه معکوس)، `bytes=150-` (خارج از محدوده) و انتهای غول‌پیکر (`bytes=0-99999999999999999999`) همه استثنای هندل‌نشده می‌دادند → 500 به‌جای 416. قابل‌کشف با اسکن خودکار درخواست‌ها.
- **فیکس:** پارس دفاعی — رنج نامعتبر → XML error `InvalidRange` با 416 طبق S3/HTTP؛ انتهای بزرگ clamp به آخرین بایت (RFC 9110 §14.2)؛ multi-range → fallback به سرو کل آبجکت.
- **تست:** ۵ تست جدید در `test_s3_range.py` (garbage/inverted/out-of-bounds/clamp/valid).

### B-048 · UI: «Other» در لجند توزیع فضا نمایش داده نمی‌شد — Severity: TRIVIAL
- **باس:** نوار توزیع (`sdOth`) دسته Other را رندر می‌کرد ولی لجند زیر نوار آن را نداشت.
- **فیکس:** آیتم Other به آرایه لجند اضافه شد (فقط وقتی حجم > 0).

## v0.15.12 — 2026-08-31 (Audit Fixes — Loop #1)

### B-041 · Download 500 برای فایل‌های با نام فارسی/یونیکد — Severity: HIGH
- **باس:** در `download.py` مقدار `Content-Disposition` مستقیم از `filename` ساخته می‌شد. Starlette هدرها را `latin-1` انکود می‌کند → نام فارسی/یونیکد = 500 در دانلود. همچنین `"` و CR/LF می‌توانستند هدر را بشکنند یا هدر تزریق کنند.
- **فیکس:** Sanitize طبق RFC 5987 → fallback اسکی + `filename*=UTF-8''...` با percent-encoding. کر/ال‌اف و کوتیشن هم خنثی می‌شوند.
- **تست:** `test_unicode_filename_download_no_500`، `test_header_injection_filename_neutralized`

### B-042 · نبود `X-Content-Type-Options: nosniff` — Severity: MEDIUM
- **باس:** پاسخ‌های `/f/{id}` این هدر را نداشتند → MIME-sniffing XSS روی فایل‌های آپلودی ممکن بود.
- **فیکس:** هدر `nosniff` به همه پاسخ‌های دانلود اضافه شد.
- **تست:** `test_download_has_nosniff`

### B-043 · نشتی کلاینت Telethon در لاگین MTProto — Severity: MEDIUM
- **باس:** در `verify-code` روی مسیرهای `need_password` / کد اشتباه `client.disconnect()` اجرا نمی‌شد → هر تلاش ناموفق یک سوکت MTProto زنده باقی می‌گذاشت. `send-code` هم فقط در دو مسیر disconnect داشت.
- **فیکس:** Disconnect در `finally` — دقیقاً یک بار، همیشه.
- **افزوده:** خطاهای تایپ‌شده فارسی (کد اشتباه/منقضی، شماره نامعتبر، رمز 2FA اشتباه، FloodWait → 429) به‌جای dump استثنا.

### B-044 · UI: دوباره‌بایند شدن هندلرهای لاگین تلگرام — Severity: LOW
- **باس:** `initTgAuthUI()` هر بار که drawer باز می‌شد `onclick` را دوباره bind می‌کرد.
- **فیکس:** گارد single-init روی `openDrawer`.

### B-045 · UI: چک `r.session_set` روی فیلد ناموجود — Severity: LOW
- **باس:** کادر وضعیت لاگین تلگرام به `session_authorized || session_set` نگاه می‌کرد؛ `session_set` هیچ‌وقت از API نمی‌آمد.
- **فیکس:** فقط `session_authorized` ملاک است.

### B-046 · UI: Cleanup جزئی — Severity: TRIVIAL
- `});;` بعد از گارد `newFolderBtn`؛ سلکتور ناسازگار `document.getElementById` داخل `guardBtn` → یکدست شد به `$()`.

## v0.15.11 — 2026-08-31 (FT: MTProto Interactive Auth + UI Hardening)

### A-014 · لاگین تعاملی MTProto از UI (API + UI)
- سه endpoint جدید: `POST /api/v1/admin/telegram/send-code`، `/verify-code` (با پشتیبانی 2FA)، `/logout`. سشن مجاز در `cfg_tg_session` ذخیره می‌شود — بدون نیاز به `anbarctl login` دستی.
- دو کادر وضعیت در UI: «لاگین فعال» (سبز) یا فرم شماره/OTP/2FA.

### A-015 · DELETE/PATCH با obj_id مسیردار
- `@router.delete("/{obj_id:path}")` و `@router.patch("/{obj_id:path}")` — id های دارای اسلش (folder-scoped) هم کار می‌کنند.

### A-016 · UI: گارد دابل‌کلیک (`guardBtn`)
- روی دکمه‌های خروج، حذف تکی/گروهی، ZIP گروهی، rotate/set secret، پوشه جدید.

### A-017 · UI: وضعیت Select-All
- دکمه «همه» با highlight (`.view-on`) و تغییر لیبل (همه/هیچ) وقتی همه فایل‌های قابل‌مشاهده انتخاب شده‌اند.

### A-018 · UI: بازخورد Rebuild کانال
- toast پیشرفت، restore متن دکمه، refresh خودکار لیست و breadcrumb بعد از rebuild.
