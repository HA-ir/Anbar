# Anbar — Bugs & Fixes (Cumulative)

> فایل تجمیعی باگ‌ها و فیکس‌ها. آخرین به‌روزرسانی: 2026-08-31 — نسخه v0.15.25

## v0.15.25 — 2026-08-31 (Improvement Plan — PERF-01)

### PERF-01 · micro-cache chunk برای seeking — Severity: عملکرد (بلندمدت)
- **باس:** disk LRU (F6) فقط دانلود کامل را سرو می‌کرد؛ هر درخواست Range (سیک مدیا در پلیر) مسیر بک‌انده می‌رفت و seek به داخل چانکی که قبلاً دیده شده = دانلود دوباره‌ی کل chunk 16MB از Telegram CDN برای پخش چند ثانیه.
- **فیکس:**
  - `ChunkMicroCache` در `src/anbar/cache.py`: LRU درون-RAM با کلید (obj_id, chunk_index) — سقف بایت (پیش‌فرض 32MB ≈ ۲ chunk)، TTL 120s، ورود chunk بزرگ‌تر از کل بودجه ممنوع، صفر نوشتن دیسک (تعهد zero-retention دست‌نخورده)، آمار تجمعی hits/misses.
  - `download.py`: `_fetch_chunk_bytes` حالا cache_key=(obj_id, chunk_idx) می‌پذیرد؛ hit از RAM برمی‌گردد، miss از بک‌اند واکشی و admit می‌شود. هر سه مسیر (filling_stream، تک‌سگمنت، prefetch depth-2) سیم‌کشی شدند.
  - knob رانتایم `seek_cache_mb` (۰ = خاموش، بازه 0–512، پیش‌فرض 32): env `ANBAR_SEEK_CACHE_MB` + runtime SPEC + `_sync_chunk_cache` برای تغییر زنده از ادمین بدون restart.
  - `remove_object(obj_id)` در مسیرهای trash و purge → chunk های آبجکت حذف‌شده از RAM هم می‌روند.
  - آمار `chunk_cache` (enabled/entries/bytes/hits/misses) در `GET /admin/status`.
- **تست:** `tests/test_seek_cache.py` — ۱۶ تست. Unit: roundtrip، شمارش miss، بودجه صفر = خاموش، chunk oversized، eviction LRU، مقاومت با touch، TTL expiry، replace هم‌کلید، remove_object، close. E2E با شمارنده FakeBackend: دو seek متوالی در یک chunk → `open_calls` فقط +1 (قبلاً +2)، درستی بایت‌ها روی مرز chunk‌ها و انتهای فایل، گزارش status، override=0 → هر seek می‌رود بک‌اند، delete → entries صفر. کل ۳۳۲ → **۳۴۸ سبز**؛ ruff روی فایل‌های تغییر یافته تمیز.
- **دیپلوی + E2E پروداکشن (2026-08-31 23:5x Tehran):** بیلد `anbar:prod` (sanity 0.15.25)؛ `docker compose up -d`؛ healthz محلی و https هر دو `0.15.25`. E2E واقعی روی loopback با payload تصادفی 40MB (3 chunk): baseline status → seek_cache_mb زنده 32→48 → آپلود → seek A (chunk0، miss) → seek B (chunk0، **RAM hit**) → seek مرزی روی درز chunk0/chunk1 → بایت‌ها دقیق در هر سه → status: `hits=2, misses=2, entries=2, bytes=33554432` → purge → `entries=0` + 404. **۲۱/۲۱ PASS**؛ knob به 32 برگردانده شد؛ آبجکت تست purged.
- **یادداشت‌ها:** ۱۶ خطای ruff در فایل‌های خارج از این تغییر (scripts/bench_10g_hybrid.py و…) از قبل وجود داشتند — عمداً دست نخوردند تا این commit تک‌موضوعی بماند. نکته بلندمدتِ «chunk کوچک‌تر برای مدیا» همچنان ایده آینده است و به این فیکس وابسته نیست.

## v0.15.24 — 2026-08-31 (دیپلوی پروداکشن + E2E واقعی)

### DEP-01 · دیپلوی v0.15.24 روی Falkenstein + ریسکن واقعی — Severity: ops
- **انجام شد (2026-08-31 22:19 Tehran):**
  - `uv lock` بعد از bump (قانون اسکیل — جلوگیری از dirty tree) → commit `aebe0d2`.
  - بیلد `anbar:prod` (sanity: image reports `0.15.24`)، `docker compose up -d` بک‌گراند، کانتینر recreate و healthy.
  - healthz محلی و https هر دو `version 0.15.24` ✓ · جدول `jobs` در DB پروداکشن ساخته شد (migration خودکار) ✓ · endpoint جدید `/api/v1/admin/jobs` (بدون توکن 401، با توکن `{"jobs":[],"count":0}`) ✓.
  - **E2E واقعی backup:** `POST /admin/backup/telegram` → `{"status":"queued","job_id":...}` → poll → `state=done` با `file_id`/`message_id` واقعی (376KB به کانال ذخیره) ✓.
  - **E2E واقعی ingest از طریق صف:** آپلود README از GitHub → `state=done`، 29668 bytes، 1 chunk، sha256 ثبت؛ دانلود فایل 200 OK؛ سپس trash ✓.
  - **ریسکن واقعی restart:** ردیف `running` دستی در DB پروداکشن نوشته شد → `docker restart anbar-anbar-1` → state = `interrupted` با پیام «server restarted while this job was in flight» ✓ (دقیقاً مطابق طراحی §5) — سپس حذف ردیف با `DELETE /admin/jobs/{id}` ✓.
- **بنچمارک ARCH-01 (معوقه که بسته شد):** 8MB=12.3 · 32MB=17.8 · 128MB=17.8 MB/s آپلود → **~3.4×** سقف تکی (5.2). جدول جدید در README (بخش Speed test v0.15.24).

## v0.15.24 — 2026-08-31 (Improvement Plan — ARCH-02)

### ARCH-02 · صف job داخلی (SPOF عملیات سنگین) — Severity: معماری
- **باس:** عملیات سنگین (backup به تلگرام، rebuild کانال، ingest) داخل همون request handler اجرا می‌شد؛ crash/restart وسط کار = کار گم + ادمین بی‌خبر، و هیچ صفی برای ترتیب/سقف همزمانی وجود نداشت.
- **فیکس:**
  - جدول `jobs` در همون SQLite (بدون وابستگی جدید): state machine کامل queued→running→done/error/interrupted/cancelled با created_at/started_at/finished_at.
  - `JobQueue` (src/anbar/jobqueue.py): worker pool asyncio با cap per-kind (ingest_url=2 مطابق `_SEM` قبلی، backup_now=1، channel_rebuild=1)، FIFO منصفانه، `submit/set_progress/finish/get/list/cancel/delete/prune/mark_interrupted_on_boot/stop`.
  - restart semantics: هر ردیف queued/running در بوت بعدی → `interrupted` با پیام واضح؛ shutdown هم ردیف نیمه‌کاره را صادقانه error می‌کند (دیگر ردیف phantom نمی‌ماند).
  - ingest: ردیف durable موقع submit ساخته می‌شود؛ progress و نتیجه mirror می‌شود؛ endpoint status بعد از restart از DB fallback می‌خواند (قبلاً 404).
  - `POST /admin/backup/telegram` و `POST /admin/channel/rebuild`: فوری `{"status":"queued","job_id":...}` برمی‌گردانند و کار در صف اجرا می‌شود؛ بدنه rebuild به `_rebuild_scan` استخراج شد. مسیر inline برای حالت بدون صف حفظ شد.
  - API ادمین: `GET /api/v1/admin/jobs` (فیلتر state/kind)، `GET /admin/jobs/{id}`، `POST /admin/jobs/{id}/cancel` (فقط queued؛ running→409)، `DELETE /admin/jobs/{id}` (فقط finished؛ 409).
  - UI: دکمه‌های backup و rebuild حالا job را poll می‌کنند (سقف 5 و 10 دقیقه) و نتیجه/خطای واقعی را نشان می‌دهند.
  - prune: ردیف‌های finished بعد از 1h در prune loop موجود حذف می‌شوند.
- **تست:** `tests/test_jobqueue.py` — ۲۰ تست (چرخه کامل، خطای handler، cap واقعی per-kind، no-handler، restart واقعی app با فایل DB مشترک → interrupted، prune/cancel/delete، API ادمین + auth، backup E2E از طریق صف). `test_backup_and_stats` برای جریان queued→poll→done به‌روز شد. کل ۳۱۲ → ۳۳۲ سبز.
- **یادداشت‌ها:** دو باگ واقعی حین تست گرفته شد (no-handler باعث Task exception و ردیف running معلق می‌شد؛ `get()` result را parse نمی‌کرد). ZIP عمداً روی صف نرفت — streaming است و event-loop را بلاک نمی‌کند. pacing تلگرام دست‌نخورده (صف فقط ترتیب می‌دهد، ارسال همچنان در storage layer pace می‌شود). تست E2E کامل ریسکن واقعی روی سرور Falkenstein هنوز اجرا نشده.

## v0.15.23 — 2026-08-31 (Improvement Plan — ARCH-01)

### ARCH-01 · آپلود چند-توکنی روی BotPool — Severity: معماری (آخرین مورد باز IMPROVEMENT_PLAN)
- **باس:** BotPool برای دانلود round-robin داشت ولی `_store_stream` همه‌ی chunk ها را از توکن اول (`app.state.bot_client = bot_pool.primary`) می‌فرستاد؛ سقف واقعی آپلود ~5.2MB/s با وجود چند توکن.
- **فیکس:**
  - `Chunk.backend` جدید (کلید اختیاری `"k"` در manifest JSON). کلید `"b"` قبلاً برای `bot_file_id` اشغال بود → انحراف از طراحی اولیه (§4.1 که `"b"` را پیشنهاد داده بود) و ثبت آن در Change Log.
  - `BotPool`: نام پایدار هر عضو (`bot`, `bot:1`, …) در ساخت، `by_name()`, `names()`, `contains()`, `mark_flood()` و `next()` با فیلتر FloodWait (TTL 60s، fallback به عضو اول وقتی همه pause هستند).
  - `ObjectService`: با pool چند-عضویِ **مالکِ** بک‌اند اصلی، هر chunk به عضو بعدی سالم می‌رود و نامش در chunk ثبت می‌شود؛ `FloodBudgetExceeded` → عضو pause و یک retry روی عضو دیگر قبل از 504. بدون pool / تک‌عضو / hybrid (mtproto اصلی + pool بات) → رفتار قبلی دقیقاً حفظ شد (`_distribute=False`).
  - مسیرهای دانلود per-chunk از عضو نگهدارنده: `_fetch_chunk_bytes` (streaming + range)، ZIP (`fetch_chunk`)، S3 GET و DELETE، rollback و `_purge_object_blobs` (پارامتر جدید `pool`; call sites در download.py و admin.py سیم شد).
  - checkpoint آپلود (`upres:`) حالا `"k"` هر chunk را هم حمل می‌کند؛ resume چند-توکنی درست ادامه می‌دهد.
- **تست:** `tests/test_arch01_multi_backend.py` — ۱۱ تست: نام‌گذاری پایدار اعضا + by_name/contains، roundtrip manifest با `"k"` (و دست‌نخوردن `"b"`)، توزیع دقیق ۹ chunk روی ۳ عضو، تک‌عضو = رفتار legacy، hybrid توزیع نمی‌کند، FloodWait skip + انقضای TTL، purge و rollback از عضو درست، resume با حفظ نام اعضا، دانلود route-level از عضو نگهدارنده. کل مجموعه ۳۰۱ → ۳۱۲ سبز.
- **یادداشت:** بنچمارک واقعی >3x روی سرور Falkenstein (با ۳ توکن واقعی) هنوز اجرا نشده؛ بخش بنچمارک README فقط قابلیت را مستند کرده — اعداد بعد از تست تولیدی اضافه می‌شود.

## v0.15.19 — 2026-08-31 (Audit Fixes — Loop #9)

### B-057 · Path traversal در ابزار بازیابی آفلاین (recover.py) — Severity: HIGH
- **باس:** `recover_files()` مسیر خروجی را `out_path / clean_name` می‌ساخت در حالی که `clean_name` مستقیم از caption تلگرام می‌آمد. caption مثل `/etc/evil.txt` یا `../../evil.sh` از پوشه خروجی خارج می‌شد (نوشتن دلخواه در سناریویی که ورودی‌اش — دامپ کانال — باید غیرقابل‌اعتماد فرض شود).
- **فیکس:** basename با `PurePosixPath` (هم‌سان با `api/ingest.py` سمت سرور)، fallback به `recovered_<id>.bin` برای نام خالی/`.`/`..`، و بازبینی containment نهایی با `resolve()` + `is_relative_to()`.
- **تست:** `tests/test_v01519_audit.py` — ۸ حالت نام مخرب، بازیابی end-to-end با caption مسیردار (فایل باید داخل out_dir بنویسد)، caption `..` → fallback.

### B-058 · Secrets در Docker build context — Severity: HIGH
- **باس:** `.dockerignore` وجود نداشت و `docker/compose.yaml` با `context: ..` بیلد می‌کند → هر بیلد (compose محلی، CI smoke، publish GHCR) کل ریپو از جمله `.env` (کلیدهای admin/API)، `data/`، `secrets/` (سشن MTProto)، `.git` و `.venv` را به دیمون داکر می‌فرستاد.
- **فیکس:** افزودن `.dockerignore` — حذف همه مسیرهای حامل secret و سنگین. (نکته: `*.md` حذف نشد چون Dockerfile `README.md` را COPY می‌کند.)
- **تست:** build کامل ایمیج + healthz smoke (پاس: `{"status":"ok"}`)؛ CI موجود build را پوشش می‌دهد.

### A-020 · پوشش تست gapها (Loop #9)
- تست مستقیم برای `ratelimit.py` (پنجره ثابت، Retry-After، باکت جدا per-obj، هش شدن کلید در upload، limit=0) و `qrcode.py` (SVG لینک واقعی ۱۷۴ کاراکتری، خطای تمیز payload طولانی، sanity فایندر الگو) — قبلاً هر دو صفر تست مستقیم بودند. تست‌ها 243 → 260.


## خلاصه Audit Loops (دور به دور)

| Loop | نسخه | یافته‌ها | نتیجه |
|---|---|---|---|
| #1 | v0.15.12 | B-041 (download 500 با نام فارسی، HIGH)، B-042 (nosniff)، B-043 (نشتی کلاینت Telethon)، B-044–B-046 (UI) | ۶ فیکس + ۶ تست — پوشش: auth.py، webauth، ratelimit، zipper، qrcode، links، download، upload، admin |
| #2 | v0.15.13 | B-047 (S3 Range خراب → 500، MED)، B-048 (لجند «Other»، TRIVIAL) | ۲ فیکس + ۵ تست — پوشش: s3.py، db.py، objects.py |
| #3 | — | بازرسی وضعیت (git sync، ruff، 220 تست، prod health، TODO/console.log) | بدون باگ جدید |
| #4 | v0.15.14 | B-049 (Stored XSS گالری آلبوم، HIGH) | ۱ فیکس + ۳ تست |
| #5 | v0.15.15 | B-050 (XSS لیست فایل Mini App، HIGH) | ۱ فیکس + ۲ تست — پوشش: bot_backend/pool/harvester، mtproto_backend، ingest، cli، notify |
| #6 | v0.15.16 | B-051 (نشتی فایل temp در DiskLRU، MED)، B-052 (login 500 با JSON غیر-object، LOW)، B-053 (مرگ حلقه prune روی خطای گذرا، LOW) | ۳ فیکس + ۶ تست — ساخت AUDIT_COVERAGE.md؛ پوشش: cache، config، crypto، main، runtime، self_healing، storage/base، api/web |
| L7 | v0.15.17 | B-054 (نشت توکن بات و api_hash خام در پاسخ telegram-config، MED)، B-055 (500 با ردیف خراب chunk_size در .env، LOW)، B-056 (پیش‌پرکردن input با hash خام در داشبورد، LOW) | ۳ فیکس + ۴ تست — پوشش: admin.py کامل (۱۲۸۰ خط، همه endpointها)، miniapp.html کامل |
| L8 | v0.15.18 | بدون باگ جدید — ۱۰ تست سخت‌شدنی اضافه شد (info metadata، S3 traversal sweep، header injection، log-leakage guard) | ممیزی: GET info، POST link، DELETE، S3 کامل، webauth/2FA، sweep سراسری، nginx |
| L9 | v0.15.19 | B-057 (Path traversal در recover.py، HIGH)، B-058 (secrets در build context داکر، HIGH) | ۲ فیکس + ۱۴ تست — پوشش کامل: ۱۰ قطعه index.html، زیرساخت (Dockerfile/compose/CI/bench)، recover.py، gap-analysis تست‌ها — پوشش دور ۱۰۰٪ |

**جمع:** ۱۸ باگ (B-041…B-058) · تست‌ها 209 → 260 · سطح‌ها: 5×HIGH، 5×MEDIUM، 6×LOW، 2×TRIVIAL
**Loop #10 باز شد (v0.15.19):** همه آیتم‌های coverage به `[ ]` برگشتند — دور بعدی ممیزی کامل از صفر.
**درس تکرارشونده:** الگوی «innerHTML بدون escape با داده کاربر» دو بار (آلبوم + miniapp) — بعد از این، همه render pathهای جدید باید esc/escape دارند.
**CI:** یک خطای E501 (خط طولانی) هم پس از loop #1 گرفته و فیکس شد.

## v0.15.17 — 2026-08-31 (Audit Fixes — Loop #7)

### B-054 · نشت توکن‌های بات و api_hash خام در `GET /api/v1/admin/telegram-config` — Severity: MEDIUM
- **باس:** پاسخ endpoint به‌همراه نسخه‌های mask شده، `bot_tokens_raw` (کل رشته ANBAR_BOT_TOKENS) و `api_hash` خام را هم برمی‌گرداند — هر زمینه‌ای که پاسخ ادمین را ببیند (کش مرورگر، تب داشبورد، لاگ پراکسی) اعتبارنامه‌های زنده تلگرام را می‌گیرد. داشبورد هم این مقادیر خام را داخل inputها pre-fill می‌کرد (hash در فیلدی که اول password بود ولی با value assignment قابل‌دید می‌شد).
- **فیکس:** پاسخ فقط masked tokens + count دارد؛ `api_hash` هم mask شد. UI: فیلد توکن/hash همیشه خالی با placeholder ماسک‌شده؛ ارسال فقط وقتی ادمین مقدار تایپ کند (خالی = حفظ مقدار فعلی؛ ذخیره ساده نه leak می‌کند نه wipe).
- **تست:** ۳ تست در `test_admin_secret_exposure.py` + آپدیت `test_telegram_config.py`.

### B-055 · `telegram-config` با ردیف خراب ANBAR_CHUNK_SIZE_MB → 500 — Severity: LOW
- **باس:** `int(env_vars.get(...))` با مقدار غیرعددی در .env، ValueError هندل‌نشده → 500.
- **فیکس:** fallback به مقدار زنده settings.
- **تست:** `test_telegram_config_env_with_garbage_chunk_size`.

### B-056 · پیش‌پرکردن فیلد API hash داشبورد با مقدار خام — Severity: LOW
- **باس:** زیرمجموعه B-054 سمت UI — رفع شد با همان تغییر (فیلد همیشه خالی + placeholder ماسک).
- **تست:** پوشش با تست‌های B-054.

### نکات audit شده در این دور (بدون باگ)
- `miniapp.html` کامل: auth با initData از تلگرام (بدون کلید در کد)، esc در renderList (فیکس B-050 قبلی)، upload flow با هندل خطا، جستجو/فیلتر سالم.
- `admin.py` باقی endpointها: require_admin سراسری، s3/request puzzles، cache purge (rebuild)، auth toggle، rotate-secret (حداقل طول ۸)، settings validation (bool guard)، import backup (ValueError→400)، channel rebuild (حذف telethon leak قبلی)، folder ops (move-into-itself guard)، trash restore/purge، audit-logs، api-keys (کلید بعد از ساخت فقط یک‌بار)، link manage page (escape با html.escape + quote=True).
- **درس ایمنی تست:** تست‌هایی که مسیر env را لمس می‌کنند باید روی tmp isolate شوند — روی هاست دیپلوی، `_get_env_file_path()` مسیر واقعی /opt/anbar/.env را برمی‌گرداند (یک تست واقعاً channel id پرود را بازنویسی کرد — ترمیم شد).

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

## v0.15.20 — 2026-08-31 (Improvement Plan — Batches 1-4)

پیاده‌سازی ۱۷ آیتم از IMPROVEMENT_PLAN.md (MP-01/02، SEC-01…05، ARCH-03/04، PERF-02/04، UX-01…04، DOC-01، QUAL-03). خلاصه:

- **MP-01**: resume روی `/api/v1/upload` (multipart) هم فعال شد — قرارداد مشترک با `upload/raw` (X-Upload-Id / X-Resume-From).
- **MP-02**: نشت kv بسته شد — `upres:` بعد از commit حذف + prune دوره‌ای 24h (فرمت envelope با `_ts`).
- **SEC-01**: XFF فقط از peer لوکال‌هاست پذیرفته می‌شود و آخرین hop برمی‌دارد (سازگار با nginx loopback).
- **SEC-02**: کلید admin دیگر از `?k=` پذیرفته نمی‌شود (breaking عمدی؛ UI از cookie استفاده می‌کند).
- **SEC-03**: fallback بی‌صدای passphrase ZK → کلید API حذف شد؛ بدون passphrase آپلود ZK خطای واضح می‌دهد.
- **SEC-04**: نوشتن `.env` اتمیک (tmp + fsync + os.replace + `.bak`).
- **SEC-05**: import بکاپ با سقف 256MB و streaming به tmp (بدون OOM).
- **PERF-02**: GZipMiddleware (min 1000B؛ مسیرهای media مستثنا) + gzip directives در nginx example.
- **PERF-04**: `Cache-Control: private, max-age=3600` روی پاسخ کامل 200 آبجکت.
- **ARCH-03**: prune خودکار JOBS تمام‌شده‌ی >1h.
- **ARCH-04**: retention 90 روزه برای audit_logs (در حلقه prune موجود).
- **UX-01**: همه‌ی prompt()/confirm() بومی → modal های RTL-safe (`askText`/`askConfirm`).
- **UX-02**: داشبورد limit=500 (سقف پنهان ۵۰ برداشته شد).
- **UX-03**: re-attach job اینجست پس از reload (sessionStorage).
- **UX-04**: بنر خطای شبکه با retry در داشبورد.
- **DOC-01**: نام‌های env سند DR به نام‌های واقعی config اصلاح شد.
- **QUAL-03**: برچسب گمراه‌کننده «رمزنگاری» → «رمزنگاری caption و متادیتا».

تست: 243 → **284 passed**. فایل‌های جدید تست: `test_v01520_improvements.py`، `test_v01520_batch2.py`، `test_v01520_batch3.py`.

## v0.15.21 — 2026-08-31 (Improvement Plan — QUAL-01 + QUAL-02)

### R-001 · ObjectService مشترک (QUAL-01) — Severity: REFACTOR
- **باس:** بلوک‌های rollback/commit بین `upload.py` و `ingest.py` کپی‌پیست بودند و drift واقعی داشتند (caption و harvester فقط در مسیر آپلود).
- **فیکس:** ماژول `src/anbar/object_service.py` — کلاس `ObjectService` با store/rollback/commit مشترک؛ هر دو route روی آن.
- **تست:** `tests/test_object_service.py` — ۷ تست (شامل E2E ingest که باگ `nonlocal total_in` جاافتاده را کشف کرد).

### F-001 · miniapp احراز هویت واقعی (QUAL-02) — Severity: MEDIUM
- **باس:** `verify_telegram_init_data` نوشته و تست شده بود ولی به هیچ endpoint وصل نبود؛ miniapp در auth=on عملاً غیرقابل استفاده بود.
- **فیکس:** `POST /ui/miniapp/session` (rate-limited، audited، سشن admin مثل login؛ بدون توکن → 503) + `ensureSession()` در miniapp با `credentials: include` روی همه fetch ها.
- **تست:** `tests/test_miniapp_session.py` — ۵ تست (امضای بد/منقضی 401، بدون توکن 503، جریان کامل admin، نقش سشن).

تست: 284 → **296 passed**.

## v0.15.22 — 2026-08-31 (Improvement Plan — PERF-03)

### P-001 · thumbnail واقعی برای گالری (PERF-03) — Severity: PERF
- **باس:** هر `<img>` گالری کل آبجکت را از تلگرام می‌کشید؛ گالری ۵۰ عکسی = ۵۰ دانلود کامل.
- **فیکس:** ماژول `thumbs.py` — تولید ≤256px (JPEG/WebP) هنگام آپلود تصویر با Pillow (انتخاب کاربر)، ذخیره در `data/thumbs/`، best-effort (خرابی تصویر آپلود را نمی‌شکند). endpoint `GET /f/{id}/thumb` با همان auth matrix؛ `hasThumb` در لیست ادمین؛ گالری با fallback به object کامل؛ purge → حذف thumb.
- **کشف حین تست:** `has_thumb` فقط `.webp` را چک می‌کرد در حالی که خروجی RGB به JPEG می‌رود؛ `list_objects` ستون `content_type` را SELECT نمی‌کرد. هر دو رفع شد.
- **تست:** `tests/test_thumbs.py` — ۵ تست؛ کل **301 passed**.

وابستگی جدید: `pillow>=12.3.0` (با تأیید کاربر). طراحی ARCH-01 (آپلود چند-توکنی) و ARCH-02 (صف job) در بخش ۴ و ۵ IMPROVEMENT_PLAN.md نوشته شد — اجرا جلسه بعد.
