# Anbar — Improvement Plan (Working Record)

> **Created:** 2026-08-31 11:55 (Asia/Tehran)
> **Last update:** 2026-08-31 22:25 (Asia/Tehran)
> **Status:** 22 از 23 مورد انجام شد ✅ — ARCH-02 (v0.15.24) انجام شد **و روی پروداکشن دیپلوی + E2E verify شد**. باقیمانده: فقط PERF-01 (بلندمدت، micro-cache برای seeking).
> **Baseline:** v0.15.19 @ c00fc76 — 260 tests passing. الان: 332 tests passing.
> **پروداکشن:** dl.amiri-dev.ir = **v0.15.24** @ aebe0d2 (دیپلوی 2026-08-31 22:19 Tehran، healthz تأیید، ریسکن restart هم پاس شد). بنچمارک ARCH-01 هم گرفته شد (~3.4×).

این فایل نقش working record دارد: هم پلن اولیه، هم وضعیت لحظه‌ای. بعد از هر فیکس،
وضعیت در جدول به‌روز و یک ورودی در Change Log اضافه می‌شود.

---

## 1) جدول ایرادات

| ID | Title | Category | Location | Description | Proposed Fix | Priority | Status |
|----|-------|----------|----------|-------------|--------------|----------|--------|
| MP-01 | Resume فقط در upload_raw کار می‌کند | معماری | `src/anbar/api/upload.py:221` (`upload_multipart`) | UI (`ui/index.html:3471`) روی `/api/v1/upload` هدرهای `X-Upload-Id` / `X-Resume-From` می‌فرستد ولی فقط `upload_raw` آن‌ها را می‌خواند. Retry یعنی آپلود کامل از صفر — feature ادعاشده در docstring عملاً برای مسیر اصلی UI مرده است. | خواندن هدرها در `upload_multipart` و پاس دادن `upload_id` / `resume_from` به `_store_stream` (همان کاری که raw می‌کند). تست جدید: resume end-to-end روی multipart. | 🔴 بحرانی | ✅ Done |
| MP-02 | نشت checkpoint های `upres:` و `rev:` در kv | معماری | `src/anbar/api/upload.py:107`؛ `rev:` در `api/download.py` (mint_link) | docstring ادعای انقضای 24h دارد ولی هیچ TTL یا `kv_delete` در مسیر موفق وجود ندارد. در سرور تولیدی ۴ کلید `upres:` یتیم تأیید شد. رشد بی‌حد جدول kv. | حذف checkpoint بعد از commit موفق؛ prune دوره‌ای (در `_prune_rate_loop` موجود) برای `upres:`/`rev:` قدیمی‌تر از 24h. | 🔴 بحرانی | ✅ Done |
| SEC-01 | XFF قابل جعل در rate limiting | امنیت | `src/anbar/ratelimit.py:_client_ip` | اولین entry از `X-Forwarded-For` به‌عنوان IP گرفته می‌شود؛ کلاینت مستقیم (یا پشت پراکسی ناآگاه) می‌تواند هدر جعلی بفرستد و limit هر IP را دور بزند. | آخرین hop معتبر (یا فقط وقتی درخواست از loopback/reverse-proxy آمده هدر را قبول کن). پیاده‌سازی: اولویت `request.client.host`؛ فقط اگر اتصال از loopback بود XFF خوانده شود. | 🔴 بحرانی | ✅ Done |
| SEC-02 | کلید admin در query string (`?k=`) | امنیت | `src/anbar/api/download.py:193-209` | fallback واکشی مدیا `?k=...` کلید اصلی ادمین را می‌پذیرد؛ کلید در لاگ‌ها، تاریخچه مرورگر و referrer می‌نشیند. | پذیرش `?k=` فقط برای کلیدهای dynamic (api_keys جدول)؛ admin key از query حذف شود. UI به‌جای `?k=` از session cookie استفاده می‌کند (همین حالا پیش‌فرض است). | 🟢 quick win | ✅ Done |
| SEC-03 | passphrase ZK به‌صورت بی‌صدا = کلید API | امنیت | `src/anbar/ui/index.html:3374` (`getClientZkPassword`) | اگر کاربر passphrase ست نکرده باشد، `_apiKey` به‌عنوان passphrase رمزنگاری client-side استفاده می‌شود → فایل «رمزشده» در واقع با کلید ادمین قابل رمزگشایی است و کاربر فکر می‌کند ZK دارد. | حذف کامل fallback؛ همیشه prompt (و در صورت خالی بودن، آپلود ZK را با خطای واضح رد کن). | 🟢 quick win | ✅ Done |
| SEC-04 | نوشتن `.env` غیراتمیک از API | امنیت | `src/anbar/api/admin.py:_write_env_dict` | `path.write_text` مستقیم؛ crash وسط نوشتن = `.env` نیمه‌کاره و سرویس بعد از restart بالا نمی‌آید. | نوشتن در tmp هم‌مسیر + `os.replace` اتمیک + نگه‌داشتن نسخه `.bak`. | 🟢 quick win | ✅ Done |
| SEC-05 | import بکاپ بدون سقف حجم در RAM | امنیت | `src/anbar/api/admin.py:backup_import` | `await file.read()` کل فایل بکاپ را یک‌جا در حافظه می‌خواند؛ بکاپ چندصدMB = OOM روی سرور کوچک. | سقف حجم (مثلاً 64MB) با چک `Content-Length` + خواندن streaming به tmp، بعد `restore_bytes` از فایل. | 🟡 متوسط | ✅ Done |
| ARCH-01 | آپلود تک‌توکنی روی BotPool | معماری | `src/anbar/main.py:67` (`app.state.bot_client = bot_pool.primary`) | BotPool برای دانلود round-robin می‌کند ولی آپلود همیشه از توکن اول می‌رود؛ سقف واقعی ~5.2MB/s (بنچمارک README). | توزیع chunk ها بین بک‌اندهای pool در `_store_stream`/`on_chunk` (هر chunk از backend بعدی). دقت: manifest باید backend هر chunk را نگه دارد (ستون backend فعلاً سراسری است → نیازمند طراحی). | 🔵 بلندمدت | ✅ Done (v0.15.23) |
| ARCH-02 | تک‌پروسه‌ای / SPOF پروسه | معماری | کل استک (uvicorn worker=1) | عملیات سنگین (backup، rebuild کانال، ZIP) event-loop را بلاک می‌کند؛ worker اضافه ممکن نیست چون pacing و harvester per-process هستند. | ✅ Done (v0.15.24): صف job داخلی SQLite (`jobs` table) — طراحی §5 اجرا شد. `jobqueue.py`: JobQueue با worker pool asyncio و cap per-kind (ingest=2، backup=1، rebuild=1)، FIFO منصفانه، mark_interrupted_on_boot (صف/running بعد از restart → interrupted)، prune بعد از 1h در prune loop موجود. ingest و backup/telegram و channel/rebuild همه از صف رد می‌شوند + endpoint های ادمین `GET /admin/jobs[/{id}]`، `POST /admin/jobs/{id}/cancel`، `DELETE /admin/jobs/{id}`. UI دکمه‌های backup/rebuild حالا job را poll می‌کنند. status ingest بعد از restart از ردیف DB fallback می‌خواند (دیگر 404 نمی‌دهد). pacing تلگرام دست‌نخورده (صف فقط ترتیب می‌دهد). | ۲۰ تست `tests/test_jobqueue.py` (چرخه کامل، cap per-kind، interrupt-on-boot با restart واقعی app، prune/cancel/delete، API ادمین، backup از طریق صف)؛ کل 332 سبز؛ ruff تمیز؛ node --check پاس | ZIP عمداً روی صف نرفت — streaming است و بلاک‌کننده نیست (همان بهانه طراحی §5). auto-backup روزانه هم همان‌قدر سبک ماند. |
| ARCH-03 | `JOBS` ingest هرگز پاک نمی‌شود | معماری | `src/anbar/api/ingest.py:37` | نشت حافظه آهسته؛ با restart هم لیست job گم می‌شود و UI فقط 404 می‌بیند. | prune خودکار job های تمام‌شده قدیمی‌تر از 1h (در job loop موجود) + حد نصاب تعداد. | 🟢 quick win | ✅ Done |
| ARCH-04 | audit_logs بدون retention | کیفیت کد | `src/anbar/db.py` (audit_logs) | جدول لاگ بی‌نهایت رشد می‌کند؛ prune ای برای آن نیست (فقط rate پرune می‌شود). | در `_prune_rate_loop` موجود، حذف رکوردهای audit قدیمی‌تر از 90 روز (قابل تنظیم runtime). | 🟢 quick win | ✅ Done |
| PERF-01 | Range → دانلود کامل chunk از تلگرام | عملکرد | `src/anbar/api/download.py:_fetch_chunk_bytes` | کلیک وسط ویدیوی بزرگ = واکشی کل chunk 16MB از Telegram CDN برای پخش چند ثانیه. | micro-cache کوتاه‌عمر آخرین chunk (برای seeking)؛ بلندمدت: chunkهای کوچک‌تر برای مدیا. | 🔵 بلندمدت | ⬜ Not started |
| PERF-02 | پاسخ‌ها gzip نمی‌شوند | عملکرد | `src/anbar/main.py` / `nginx/anbar.conf.example` | index.html 210KB خام (~52KB gzip) و هیچ GZipMiddleware یا gzip در nginx نیست؛ هر لود اولیه سنگین است. | افزودن `GZipMiddleware` (minimum_size=1000) در main.py + خطوط gzip در nginx example. | 🟢 quick win | ✅ Done |
| PERF-03 | thumbnail ندارند previewها | عملکرد | `src/anbar/ui/index.html:2136` | هر `<img>` گالری کل آبجکت را از تلگرام می‌کشد؛ گالری ۵۰ عکسی = ۵۰ دانلود کامل. | تولید thumbnail کوچک هنگام آپلود تصویر (Pillow در sidecar که گزینه‌ای است) یا حداقل `Range` برای preview و پیش‌فرض خاموش در network کند. | 🟡 متوسط | ✅ Done |
| PERF-04 | Cache-Control روی آبجکت‌ها نیست | عملکرد | `src/anbar/api/download.py` (headers) | آبجکت immutable است ولی مرورگر هر بار دوباره می‌پرسد؛ ETag/304 هست ولی برای مرور تکراری هنوز round-trip لازم است. | `Cache-Control: private, max-age=3600` روی پاسخ کامل 200 آبجکت (نه signed links عمومی پرترافیک بدون صلاحدید). | 🟢 quick win | ✅ Done |
| UX-01 | ۱۵+ prompt()/confirm() بومی | UI-UX | `src/anbar/ui/index.html` (1668، 1942، 1977، 2595، 3385 و...) | دیالوگ‌های native در RTL/موبایل ناسازگار و ناخوانا؛ تجربه‌ی ناهمگون با modal های موجود. | مهاجرت تدریجی به modal موجود (الگوی `moveModal`)؛ شروع با rename/purge/ZK-pass. | 🟡 متوسط | ✅ Done |
| UX-02 | سقف ۵۰ فایل در داشبورد | UI-UX | `src/anbar/ui/index.html:1829` + `admin.py:objects` (پیش‌فرض limit=50) | UI بدون پارامتر می‌خواند → بعد از ۵۰ فایل بقیه نامرئی؛ سرچ هم روی همین ۵۰ تاست. | UI: `?limit=500` + ایندیکس «نمایش N از M» + scroll-pagination ساده. | 🟢 quick win | ✅ Done |
| UX-03 | ingest: جریان خطا و re-attach job | UI-UX | `src/anbar/ui/index.html:pollIngest` | poll ثابت 1.2s؛ ری‌لود صفحه = گم‌شدن job؛ لیست job فعال برای re-attach نیست. | ذخیره‌ی job_id فعال در sessionStorage + re-attach هنگام boot؛ endpoint لیست job های اخیر ادمین. | 🟡 متوسط | ✅ Done |
| QUAL-01 | rollback chunking دوبار تکرار شده | کیفیت کد | `api/upload.py:_store_stream` و `api/ingest.py:_run_job` | بلوک rollback و commit عیناً copy-paste؛ هر fix باید دو جا اعمال شود (ریسک drift). | استخراج `ObjectService.store_stream()` مشترک؛ هر دو route روی آن. | 🟡 متوسط | ✅ Done |
| QUAL-02 | miniapp احراز هویت واقعی ندارد | امنیت | `src/anbar/ui/miniapp.html:73,131` + `auth.py:verify_telegram_init_data` | تابع اعتبارسنجی initData نوشته و تست شده ولی به هیچ endpoint وصل نیست؛ miniapp همیشه 401 می‌گیرد و عملاً غیرقابل استفاده در auth=on. | endpoint `/ui/miniapp/session` که initData را validate و سشن صادر کند؛ miniapp از آن استفاده کند. | 🟡 متوسط | ✅ Done |
| DOC-01 | نام‌های env در سند DR وجود خارجی ندارند | کیفیت کد | `docs/DISASTER_RECOVERY.md:~35` | سند `ANBAR_TG_BOT_TOKEN`، `ANBAR_TG_CHAT_ID`، `ANBAR_STORAGE_ENCRYPTION` را مثال می‌زند که در `config.py` وجود ندارند؛ در فاجعه واقعی گمراه‌کننده است. | اصلاح سند به نام‌های واقعی (`ANBAR_BOT_TOKEN`، `ANBAR_CHANNEL_ID`، ...) + توضیح اینکه encryption فعلاً فقط caption را رمز می‌کند. | 🟢 quick win | ✅ Done |
| QUAL-03 | برچسب گمراه‌کننده `encryption_enabled` | کیفیت کد | `src/anbar/runtime.py:35` + `api/admin.py:570-621` + UI settings | سوییچ در status/داشبورد هست ولی هیچ مسیر آپلودی chunk bytes را رمز نمی‌کند (فقط caption ها)؛ کاربر فکر می‌کند فایل‌ها at-rest رمز شده‌اند. | برچسب UI به «رمزنگاری caption/متادیتا» تغییر کند؛ یا پیاده‌سازی رمزنگاری واقعی chunk (بلندمدت). | 🟡 متوسط | ✅ Done |
| UX-04 | حذف بی‌صدا خطا در refresh | UI-UX | `src/anbar/ui/index.html:refresh()` | خطای `/admin/status` swallow می‌شود؛ کاربر نه skeleton لود اول می‌بیند نه پیام خطای شبکه. | حالت error banner + skeleton اولیه برای لیست. | 🟡 متوسط | ✅ Done |

---

## 2) ترتیب اجرای پیشنهادی

> منطق: اول باگ‌های functional-بزرگ (MP-01 چون feature ادعاشده و تست‌نشده است)، بعد
> quick win های امنیتی کم‌ریسک، بعد UX، و refactor های سنگین آخر. وابستگی‌ها با «⤴ پس از» مشخص شده.

1. **MP-01** — multipart resume (functional bug اصلی؛ تست جدید لازم دارد)
2. **MP-02** — نشت kv: cleanup بلافاصله بعد از commit + prune دوره‌ای (⤴ پس از MP-01 چون مسیر مشترک `_store_stream`)
3. **SEC-03** — حذف fallback passphrase ZK (یک‌خطی، ریسک صفر)
4. **SEC-04** — نوشتن اتمیک `.env` (کوچک، ایزوله)
5. **PERF-02** — GZipMiddleware + nginx example (کوچک، ایزوله)
6. **SEC-02** — حذف admin key از `?k=` (چک کن UI جایی `?k=` با admin key نسازد)
7. **PERF-04** — Cache-Control روی 200 کامل (کوچک)
8. **ARCH-03** — prune JOBS (کوچک)
9. **ARCH-04** — retention audit_logs (کوچک، در حلقه prune موجود)
10. **SEC-01** — XFF hardening (نیازمند دقت: پشت nginx واقعی نباید IP همه loopback شود؛ با تست)
11. **UX-02** — limit=500 + شمارنده در UI
12. **SEC-05** — سقف import بکاپ
13. **DOC-01** — اصلاح سند DR
14. **QUAL-03** — برچسب encryption (فقط UI/string، بدون تغییر رفتار)
15. **UX-04** — error banner + skeleton
16. **UX-03** — re-attach ingest job
17. **UX-01** — مهاجرت prompt/confirm به modal (تدریجی، بزرگ‌ترین دیف UI)
18. **QUAL-01** — استخراج ObjectService مشترک (refactor؛ ⤴ پس از MP-01/MP-02 تا روی کد فاینال انجام شود)
19. **QUAL-02** — miniapp initData session (نیازمند تصمیم درباره‌ی نقش miniapp)
20. **PERF-03** — thumbnail (نیازمند وابستگی Pillow یا راه‌حل sidecar — تصمیم جدا)
21. **ARCH-01** — آپلود چند-توکنی (طراحی ستون backend در manifest لازم دارد)
22. **ARCH-02** — صف job / جداسازی پروسه (بلندمدت‌ترین)

> قاعده‌ی هر fix: قبل از شروع وضعیت → 🔄؛ بعد از fix + تست سبز → ✅ + ورودی در Change Log.

---

## 3) Change Log

*(هنوز ورودی ندارد — با اولین فیکس پر می‌شود.)*

| Date/Time (Tehran) | ID | Change | Test Result | Side Notes |
|--------------------|----|--------|-------------|------------|
| 2026-08-31 12:24 | MP-01 | `upload_multipart` حالا `X-Upload-Id` / `X-Resume-From` را می‌خواند و به `_store_stream` پاس می‌دهد (همان قرارداد `upload/raw`). فایل: `src/anbar/api/upload.py` | 8 تست جدید در `tests/test_v01520_improvements.py` — همه سبز؛ کل مجموعه 268 passed | کشف حین کار: قرارداد resume «ارسال دوباره‌ی کل فایل» است؛ سرور `resume_from` chunk اول را drain می‌کند. UI از قبل با `it.resumeChunks` سازگار است — نیازی به تغییر UI نبود. |
| 2026-08-31 12:24 | MP-02 | (۱) `_commit` بعد از ثبت موفق، `upres:<id>` را از kv حذف می‌کند (`api/upload.py`). (۲) `_checkpoint` الان پاکت `{"_ts":..., "chunks":[...]}` می‌نویسد (همان فایل + سازگاری با فرمت قبلی لیست در مسیر خواندن). (۳) `db.kv_prune_prefix()` جدید در `db.py`؛ حلقه‌ی prune موجود در `main.py` هر ۱۰ دقیقه `upres:`های قدیمی‌تر از 24h را حذف می‌کند. | `test_kv_prune_prefix_drops_only_stale`، `test_kv_prune_prefix_legacy_list_format_is_ignored` سبز؛ رگرسیون resume (`test_resume.py`) هم سبز | فرمت قدیمی (لیست خام بدون `_ts`) توسط prune نادیده گرفته می‌شود — باتوجه‌به حذف-on-commit، عملاً منقضی نمی‌مانند. کلیدهای `rev:` (لینک‌ها) در این فاز دست نخوردند — حجمشان per-link است نه per-upload؛ در صورت نیاز بعداً. |
| 2026-08-31 12:24 | SEC-03 | fallback بی‌صدهای `_apiKey` به‌عنوان passphrase ZK حذف شد؛ حالا بدون passphrase، آپلود ZK با خطای واضح «Client ZK passphrase required» رد می‌شود و دانلود همیشه prompt می‌گیرد. فایل: `src/anbar/ui/index.html` (`getClientZkPassword`) | مسیر `uploadOne` از قبل `if (!pass) throw` دارد — رفتار بدون تغییر برای کاربری که passphrase ست کرده؛ تست دستی UI pending تا deploy | نکته: کاربرانی که قبلاً ناخواسته با کلید API رمز کرده‌اند، فایل‌هایشان با کلید API قابل رمزگشایی است — یک‌بار re-encrypt توصیه می‌شود (در گزارش نهایی ذکر شد). |
| 2026-08-31 12:24 | SEC-04 | `_write_env_dict` اتمیک شد: نوشتن در tmp هم‌مسیر + fsync + `os.replace` + نگه‌داشتن `.env.bak`. فایل: `src/anbar/api/admin.py` | `test_write_env_dict_atomic_and_keeps_comments`، `test_write_env_dict_creates_missing_file` سبز | `.bak` فقط آخرین نسخه را نگه می‌دارد (one-shot). در محیط container فایل `/opt/anbar/.env` mounted است — `os.replace` روی bind-mount همان filesystem است، امن. |
| 2026-08-31 12:55 | PERF-02 | `GZipMiddleware` انتخابی در `main.py` (minimum_size=1000) — HTML/JSON را فشرده می‌کند؛ مسیرهای `/f/` و `/s3/` عمداً excluded چون فشرده‌کردن media دارای Content-Length، هدر را حذف می‌کند و player ها به آن وابسته‌اند. + gzip directives در `nginx/anbar.conf.example`. | `test_dashboard_html_is_gzipped`، `test_api_json_is_gzipped`، `test_object_download_is_not_gzipped` سبز | کشف حین کار: gzip سراسری `test_full_download` را می‌شکند (حذف content-length روی پاسخ stream شده) — به همین دلیل exclusion مسیر لازم شد، نه فقط اختیاری. |
| 2026-08-31 12:55 | PERF-04 | پاسخ کامل (non-range) آبجکت‌ها حالا `Cache-Control: private, max-age=3600` دارند؛ 206 ها کش نمی‌شوند. فایل: `src/anbar/api/download.py` | `test_full_object_response_has_cache_control`، `test_range_response_has_no_cache_control` سبز | `private` انتخاب شد چون احراز هویت per-user است؛ برای object های با signed-link عمومی هم امن است (کش مرورگر کاربر، نه CDN). |
| 2026-08-31 12:55 | SEC-02 | کلید admin دیگر از طریق `?k=` پذیرفته نمی‌شود؛ فقط uploader key و کلیدهای dynamic. فایل: `src/anbar/api/download.py` (`_authenticate_download`) | `test_admin_key_in_query_string_rejected` (401)، `test_uploader_key_in_query_string_still_accepted` (200) سبز | ⚠️ Breaking-ish برای کسی که با admin key لینک `?k=` ساخته بود — لینک‌های قبلی از کار می‌افتند (حرکت عمدی امنیتی). UI از session cookie استفاده می‌کند و تأثیری نمی‌بیند. |
| 2026-08-31 12:55 | ARCH-03 | `_prune_jobs()` در `api/ingest.py`: job های done/error قدیمی‌تر از 1h هر بار که status پرسیده می‌شود prune می‌شوند (بدون loop اضافه). | `test_prune_jobs_drops_stale_finished_only` سبز | running ها هرگز prune نمی‌شوند؛ job های گم‌شده با restart همچنان 404 می‌دهند (راه‌حل کامل در UX-03). |
| 2026-08-31 13:25 | SEC-01 | `_client_ip` حالا XFF را فقط برای peer های loopback می‌پذیرد و **آخرین** hop را برمی‌دارد (nginx `$proxy_add_x_forwarded_for` کلاینت واقعی را آخر اضافه می‌کند)؛ درخواست مستقیم = IP سوکت واقعی. فایل: `src/anbar/ratelimit.py` | 4 تست جدید (`test_xff_*`) سبز؛ رفتار پشت nginx واقعی (loopback→app) تغییری نمی‌کند | ⚠️ اگر کسی اپ را پشت پراکسی غیر-local بگذارد (peer ≠ loopback)، limit بر اساس IP پراکسی می‌شود — در مستندات nginx مثال همیشه loopback است، پس سازگار. |
| 2026-08-31 13:25 | ARCH-04 | `db.audit_prune(max_age_s=90d)` جدید؛ در حلقه‌ی prune هر ۱۰ دقیقه صدا زده می‌شود. فایل: `src/anbar/db.py` + `main.py` | `test_audit_prune_deletes_only_old_records` سبز | retention ثابت 90 روز؛ در صورت نیاز بعداً به runtime setting (`cfg_audit_retention_days`) منتقل می‌شود. |
| 2026-08-31 13:25 | SEC-05 | `backup_import` حالا با سقف 256MB و streaming به فایل temp می‌خواند (1MB chunks)؛ `db.restore_from_file()` جدید بدون بارگذاری کل در RAM. فایل: `src/anbar/api/admin.py` + `db.py` | `test_backup_import_roundtrip_and_cap_rejection` (roundtrip 200 + garbage 400)، `test_restore_from_file_rejects_garbage` سبز | `restore_bytes` (قدیمی) دست‌نخورده ماند برای سازگاری با هر caller دیگر؛ tmp file در `finally` پاک می‌شود. |
| 2026-08-31 13:25 | UX-02 | داشبورد حالا `/api/v1/admin/objects?limit=500` می‌خواند — سقف پنهان ۵۰ ردیفی برداشته شد. فایل: `src/anbar/ui/index.html` | `test_objects_endpoint_accepts_limit_500` (60 آبجکت کامل برمی‌گردد) سبز | بالای ۵۰۰ آبجکت هنوز نیازمند scroll-pagination است — به‌عنوان بهبود آینده در UX-02 باقی می‌ماند (Marked partially: هسته‌ی مشکل ۵۰-tup حل شد). |
| 2026-08-31 14:10 | DOC-01 | `docs/DISASTER_RECOVERY.md`: نام‌های env غلط (`ANBAR_TG_BOT_TOKEN`/`ANBAR_TG_CHAT_ID`/`ANBAR_STORAGE_ENCRYPTION`) به نام‌های واقعی `config.py` یعنی `ANBAR_BOT_TOKEN`/`ANBAR_CHANNEL_ID` اصلاح شد + توضیح اینکه سوئیچ env برای رمز payload وجود ندارد و `ANBAR_HMAC_SECRET` فقط caption را رمز می‌کند. | — (دوکی) | کسی که DR را با داک قبلی اجرا می‌کرد، container بدون کانال بوت می‌شد — این عملاً یک bug عملیاتی بود. |
| 2026-08-31 14:10 | QUAL-03 | برچسب سوییچ `encryption_enabled` در UI (fa+en): «رمزنگاری سرتاسری/Zero-Knowledge» → «رمزنگاری caption و متادیتا» با توضیح صریح که payload فایل‌ها رمز نمی‌شوند و برای رمز واقعی باید Client ZK فعال شود. | — (دوکی؛ سازگار با تحلیل کد `encode_chunk_caption`) | ادعای امنیتی نادرست — کاربر فکر می‌کرد فایل‌هایش رمز شده در حالی که فقط کپشن رمز است. |
| 2026-08-31 14:10 | UX-04 | خطای شبکه در `refresh()` دیگر بی‌صدا نیست: بنر قرمز sticky بالای صفحه («ارتباط برقرار نشد») با click-to-retry؛ در هر دو مسیر status/objects، i18n دو زبانه. | E2E: UI رندر می‌شود و marker ها حاضرند؛ تست JS syntax OK | حالت skeleton اولیه ارزان‌تر از بنر بود ولی چون refresh سریع است، بنر کافی و ساده‌تر. |
| 2026-08-31 14:10 | UX-03 | `sessionStorage["anbar-ingest-job"]` + re-attach هنگام boot؛ در done/error/404 کلید پاک می‌شود تا poll ابدی نداشته باشیم. | E2E marker check؛ رفتار 404 پس از restart دیگر حلقه نمی‌زند | endpoint «لیست job های اخیر» فعلاً اضافه نشد — prune (ARCH-03) + re-attach پوشش اصلی را می‌دهد؛ در صورت نیاز بعداً. |
| 2026-08-31 14:10 | UX-01 | هر ۲۰ فراخوانی بومی `prompt()`/`confirm()` (۹ prompt + ۱۳ confirm، ۲ مورد در کامنت) با `askText()`/`askConfirm()` مبتنی بر modal جایگزین شد — RTL-safe، موبایل‌فرندلی، سازگار با تم. i18n: `ok`/`cancel`. | `node --check` (ES module) پاس؛ 284 تست سبز؛ 0 فراخوانی native باقی مانده | نکات فنی: `getClientZkPassword` و handler های حامل await → async شدند؛ keyboard-shortcut listener هم async شد. verify با `node --check` روی بدنه‌ی script به‌عنوان module. |
| 2026-08-31 15:50 | QUAL-01 | `src/anbar/object_service.py` جدید: کلاس `ObjectService` — store (chunker + caption + harvester + checkpoint)، rollback (best-effort، هرگز raise نمی‌کند)، commit و `describe_storage_error` همگی یک‌جا. `upload.py::_store_stream/_commit` و `ingest.py::_run_job` اکنون wrapper نازک روی آن هستند؛ هر ۳ بلوک کپی‌شده حذف شد. کشف حین کار: drift واقعی بین دو کپی (caption/harvester فقط در آپلود) دقیقاً همان ریسکی بود که آیتم پیش‌بینی کرده بود. | 7 تست جدید `tests/test_object_service.py` (rollback، swallow خطای delete، چرخه checkpoint، resume، out-of-range، E2E ingest) + کل مجموعه 296 سبز | `nonlocal total_in` جاافتاده در `_JobReader` حین نوشتن تست E2E کشف و رفع شد — تست جدید همین را پوشش می‌دهد. |
| 2026-08-31 15:50 | QUAL-02 | endpoint `POST /ui/miniapp/session` در `api/web.py`: initData با `verify_telegram_init_data` روی همه توکن‌های pool چک، rate-limit مثل login، audit (`auth.miniapp`/`auth.miniapp_denied`)، کوکی سشن admin مثل `/ui/login` (TTL همان `session_ttl`). بدون توکن بات → 503 (نه باز). miniapp: `ensureSession()` هنگام boot — اول `/ui/me`، بعد exchange با `tg.initData`؛ همه fetch ها `credentials: include`. | 5 تست جدید `tests/test_miniapp_session.py`: امضای دستکاری‌شده 401، منقضی 401، بدون توکن 503، جریان کامل → کوکی → admin objects 200، نقش admin تأیید؛ `node --check` miniapp پاس؛ کل 296 سبز | initData فقط هویت «کاربر تلگرامِ مینی‌اپ این بات» را اثبات می‌کند — نقش admin عمدی است چون miniapp ابزار owner است (همان مدل `/ui/login` که admin-key-only است). اگر بعداً miniapp عمومی شود، باید allowed-user list اضافه شود (یادداشت آینده). |
| 2026-08-31 22:25 | DEP-01 | دیپلوی v0.15.24 روی پروداکشن (Falkenstein) + E2E واقعی. uv lock بعد از bump → `aebe0d2`؛ بیلد anbar:prod (sanity 0.15.24)؛ compose up بک‌گراند؛ healthz محلی/https = 0.15.24؛ جدول jobs در DB پروداکشن (migration خودکار)؛ /admin/jobs (401 بدون توکن، خالی با توکن). E2E: backup→queued→done (file_id واقعی)، ingest URL→done (29668B، sha256، دانلود 200، trash)، ریسکن restart واقعی (docker restart → state=interrupted با پیام درست → DELETE). بنچمارک ARCH-01: 8/32/128MB = 12.3/17.8/17.8 MB/s آپلود (~3.4× سقف تکی) → جدول جدید README. | healthz دوگانه سبز؛ هر سه E2E سبز؛ کانتینر healthy؛ ریسکن پاس | کارهای معوق دیپلوی/بنچمارک/ریسکن بسته شد. باقی: فقط PERF-01. دقت: بعد از هر bump حتماً uv lock (قانون اسکیل، دوباره تأیید شد). |
| 2026-08-31 19:40 | ARCH-02 | صف job داخلی SQLite (طراحی §5). `src/anbar/jobqueue.py`: جدول `jobs` + `JobQueue` (worker pool asyncio، cap per-kind: ingest_url=2/backup_now=1/channel_rebuild=1، FIFO منصفانه با `_next_queued`). `mark_interrupted_on_boot`: ردیف‌های queued/running بعد از restart → interrupted؛ shutdown هم ردیف‌های نیمه‌کاره را صادقانه error می‌کند. ingest: ردیف durable موقع submit + mirror progress + fallback خواندن status از DB بعد از restart (دیگر 404 نمی‌دهد). backup/telegram و channel/rebuild: async → queued با job_id؛ بدنه scan به `_rebuild_scan` استخراج شد. API ادمین: `GET /admin/jobs[/{id}]`، `POST .../cancel` (فقط queued؛ running → 409)، `DELETE .../{id}` (فقط finished؛ 409). UI: دکمه‌های backup و rebuild حالا job را poll می‌کنند (سقف 5/10 دقیقه). prune ردیف‌های finished بعد از 1h در prune loop موجود. | ۲۰ تست `tests/test_jobqueue.py` + به‌روزرسانی test_backup_and_stats برای جریان queued→poll→done؛ کل 332 سبز؛ ruff تمیز؛ node --check پاس | دو باگ واقعی حین تست گرفته شد: (۱) خطای no-handler task را می‌شکست و ردیف در running می‌ماند → dispatcher-level catch؛ (۲) `get()` result را parse نمی‌کرد → الان lazy parse در خود `get()`. ZIP عمداً روی صف نرفت (streaming و غیربلاک‌کننده). |
| 2026-08-31 18:10 | ARCH-01 | آپلود چند-توکنی روی BotPool. `Chunk.backend` (کلید manifest `"k"` — کلید `"b"` از قبل برای bot_file_id اشغال بود، انحراف ثبت‌شده از §4.1)؛ `BotPool`: نام پایدار اعضا `bot`/`bot:1`/…، `by_name`/`names`/`contains`/`mark_flood`/`next` با فیلتر FloodWait (TTL 60s)؛ `ObjectService` وقتی pool چند-عضوی مالک بک‌اند اصلی است round-robin توزیع می‌کند + یک retry روی عضو دیگر هنگام FloodBudgetExceeded؛ مسیرهای خواندن/حذف per-chunk: `_fetch_chunk_bytes`، ZIP، S3 GET/DELETE، rollback، `_purge_object_blobs` (پارامتر `pool` + سیم call sites)؛ checkpoint `"k"` را حمل می‌کند (resume چند-توکنی). تک‌عضو و hybrid (mtproto+pool) دقیقاً رفتار قبلی. | ۱۱ تست `tests/test_arch01_multi_backend.py`؛ کل ۳۱۲ سبز؛ ruff فقط خطاهای pre-existing (۹ مورد، از قبل روی main بود) | بنچمارک >3x روی سرور واقعی (۳ توکن) باقی مانده — بعد از دیپلوی تولیدی اضافه می‌شود. ARCH-02 (صف job) به پلن نسخه بعد منتقل شد. |
| 2026-08-31 16:35 | PERF-03 | ماژول `src/anbar/thumbs.py`: تولید thumbnail واقعی ≤256px هنگام آپلود تصویر (Pillow — انتخاب کاربر). RGB→JPEG، RGBA→WebP، animated→فریم اول، encode در thread با سقف همزمانی ۲؛ هرگز آپلود را نمی‌شکند (best-effort). `ObjectService` chunk اول را نگه می‌دارد → `_commit` بعد از ثبت async تولید می‌کند. endpoint `GET /f/{id}/thumb` (همان auth matrix + nosniff + Cache-Control 24h). لیست ادمین پرچم `hasThumb` برمی‌گرداند (SELECT در `list_objects` ستون content_type گرفت). گالری UI از thumb استفاده می‌کند با onerror-fallback به object کامل. purge → `delete_thumb`. | ۵ تست `tests/test_thumbs.py` (تولید+سرو، 404 برای غیرتصویر/خراب + auth، لینک امضاشده، purge، پرچم hasThumb)؛ کل 301 سبز؛ node --check پاس | کشف حین کار: `has_thumb` فقط webp را چک می‌کرد در حالی که خروجی اغلب JPEG است — در تست واقعی گرفته شد. GIF متحرک و SVG از thumbnail مستثنا هستند (SVG چون Pillow decode نمی‌کند). فایل‌های موجود قبلی thumb ندارند تا آپلود مجدد — fallback به object کامل پوشش می‌دهد. |

---

## 4) طراحی ARCH-01 — آپلود چند-توکنی روی BotPool (اجرا: جلسه بعد)

> هدف: شکستن سقف ~5.2MB/s آپلود تکی. امروز `_store_stream` همه‌ی chunk ها را از
> `backend` (توکن اول pool) می‌فرستد؛ BotPool برای دانلود round-robin دارد ولی برای
> آپلود استفاده نمی‌شود.

### 4.1 — تغییر schema (پیش‌نیاز وابسته به هیچ چیز)

- **جدول objects**: ستون سراسری `backend` باقی می‌ماند (بک‌اندِ «اصلی» آبجکت) ولی منبع حقیقت per-chunk می‌شود.
- **Manifest JSON** (`objects.py::Manifest`): به هر chunk فیلد اختیاری `b` (backend name) اضافه می‌شود:
  `{"i":0,"s":N,"f":"file_id","m":msg_id,"b":"bot:2"}`. خواندن manifest قدیمی (بدون `b`)
  = همه از بک‌اند اصلی → سازگاری کامل رو به جلو؛ migration دیتابیس لازم نیست.
- **`Chunk` dataclass**: فیلد `backend: str | None = None`.
- **`download.py::_fetch_chunk_bytes`**: وقتی `chunk.backend` ست است، ref با همان
  backend ساخته شود (`pool.by_name(name)`)، نه همیشه بک‌اند اصلی. fallback به اصلی در خطا.
- **delete/purge (`_purge_object_blobs`)**: برای هر chunk با backendِ خودش حذف کند —
  در حال حاضر همه را با بک‌اند اصلی delete می‌کند که با chunk های چند-توکنی نشتی می‌دهد.

### 4.2 — الگوریتم توزیع

- **انتخاب backend per-chunk** در `ObjectService`: سازنده یک `pool` (یا `None`) می‌گیرد.
  `on_chunk` برای هر chunk جدید: `backend = pool.next()` (round-robin روی بک‌اندهای سالم pool).
- **فیلتر سلامت**: backend هایی که FloodWait فعال دارند (از `FloodBudgetExceeded` اخیر،
  نگه‌داری در memory با TTL) تا پایان window حذف می‌شوند؛ اگر همه مستثنا شدند → توکن اصلی.
- **chunk_size یکسان** بین همه بک‌اندها (4MB سقف Bot API) — الان همین است، تغییر نمی‌خواهد.
- **caption سازگار**: `encode_chunk_caption` فعلی backend-agnostic است؛ تغییری نمی‌خواهد.
- **resume/checkpoint**: فرمت envelope فعلی به chunk فیلد `b` اضافه می‌شود؛ resume قدیمی→جدید سازگار.

### 4.3 — تغییرات مسیر دانلود/حذف در صورت فقدان pool

- اگر استقرار تک-توکن است (pool.size==1)، رفتار دقیقاً مثل امروز (کدِ توزیع no-op).
- حذف chunk از backend غیراصلی وقتی آن backend down است: تلاش + log + ادامه (best-effort، مثل امروز).

### 4.4 — تست‌ها (تعریف از الان)

1. `test_multi_backend_distribution` — pool با ۳ FakeBackend؛ آپلود ۹ chunk → هر بک‌اند دقیقاً ۳ chunk.
2. `test_manifest_roundtrip_with_backend` — manifest با `b` ذخیره/خوانده می‌شود؛ قدیمی بدون `b` هم خوانده می‌شود.
3. `test_download_uses_chunk_backend` — chunk با `b:"bot:1"` از همان بک‌اند fetch می‌شود.
4. `test_purge_deletes_from_right_backends` — حذف آبجکت چند-بک‌اندی همه blob ها را پاک می‌کند.
5. `test_floodwait_skips_backend` — backend در FloodWait از چرخش خارج و بعد از TTL برمی‌گردد.
6. regression: کل مجموعه + بنچمارک README (هدف: >3x throughput با ۳ توکن).

### 4.5 — ترتیب اجرا (جلسه بعد)

1. Chunk/manifest + خواندن سازگار (بدون تغییر رفتار) + تست ۲
2. `pool.by_name` + دانلود per-chunk + تست ۳، ۴
3. توزیع در ObjectService + تست ۱، ۵
4. بنچمارک + به‌روزرسانی README

## 5) طراحی ARCH-02 — صف job داخلی (اجرا: پس از ARCH-01)

> هدف: عملیات سنگین (backup، rebuild، ZIP بزرگ، ingest) نباید event-loop را بلاک کنند و
> باید از crash/restart جان سالم به قدر کافی ببرند.

### 5.1 — مدل

- **In-process job queue** با worker pool قابل تنظیم (`JOB_WORKERS=2` پیش‌فرض)، جدول
  `jobs(id, kind, payload_json, state, progress, error, created_at, started_at, finished_at)`
  در SQLite موجود — همان DB، بدون وابستگی جدید.
- **kinds** فاز ۱: `ingest_url` (موجود، مهاجرت از JOBS dict درون حافظه)، `backup_now`، `channel_rebuild`.
- **حافظه‌ماندگاری جزئی**: job ها در DB می‌مانند؛ بعد از restart، job های `running` → `interrupted`
  (ادامه‌ی خودکار ندارند ولی پیام روشن به UI می‌دهند، برخلاف 404 امروزی — مکمل UX-03).
- **concurrency قاعده‌دار**: هر kind سقف همزمانی خودش را دارد (ingest=2 مثل امروز با `_SEM`،
  rebuild=1، backup=1) — جلوگیری از self-DDoS به تلگرام.
- **pacing سراسری**: حلقه‌ی pacing موجود تلگرام سراسری می‌ماند؛ صف فقط ترتیب می‌دهد،
  سرعت را `storage` کنترل می‌کند.

### 5.2 — API

- `GET /api/v1/admin/jobs?state=&kind=&limit=` — لیست (admin)
- `GET /api/v1/admin/jobs/{id}` — وضعیت + progress (جایگزین نهایی endpoint job های ingest)
- `POST /api/v1/admin/jobs/{id}/cancel` — فقط برای queued/runningِ cancelable (kind-dependent)
- `DELETE /api/v1/admin/jobs/{id}` — حذف رکورد (همان prune ARCH-03، ولی دستی هم)

### 5.3 — مهاجرت

- `_run_job` اینجست به worker صف منتقل می‌شود؛ `JOBS` dict → view روی DB (compat shim
  برای `pollIngest` فعلی UI تا UI هم مهاجرت کند؛ بعد از آن shim حذف).
- prune (ARCH-03) روی جدول جدید با همان قاعده 1h برای done/error.

### 5.4 — تست‌ها

1. enqueue→run→done در DB ثبت می‌شود.
2. restart شبیه‌سازی‌شده: running → interrupted، UI 404 نمی‌بیند.
3. سقف همزمانی per-kind رعایت می‌شود.
4. cancel بین chunk ها تمیز می‌ایستد (rollback از ObjectService).
5.قاعده prune روی جدول jobs.

### ریسک‌ها / نکات

- SQLite + WAL الان فعال است (ascent-data-health) — نوشتن progress هر chunk باید
  throttle شود (مثلاً هر 250ms یا هر 64 chunk) تا DB تحت فشار نرود.
- worker ها باید `asyncio` tasks داخل همان پروسه باشند (نه subprocess) — isolation
  واقعی پروسه‌ای خارج از scope این فاز است (آن می‌شود بحث worker=2 واقعی که فعلاً ممکن نیست).
