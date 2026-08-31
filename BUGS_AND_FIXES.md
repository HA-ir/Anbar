# Anbar — Bugs & Fixes (Cumulative)

> فایل تجمیعی باگ‌ها و فیکس‌ها. آخرین به‌روزرسانی: 2026-08-31 — نسخه v0.15.14

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
