# Anbar — Bugs & Fixes (Cumulative)

> فایل تجمیعی باگ‌ها و فیکس‌ها. آخرین به‌روزرسانی: 2026-09-02 — نسخه v0.15.39

## v0.15.39 — 2026-09-02

### FEAT-SUBS · زیرنویس ویدئو — پشتیبانی کامل + مدیریت ترک‌ها
- **چی ساخته شد:** ویدئو پلیر (مودال فایل) حالا زیرنویس پشتیبانی می‌کند — منوی CC مرورگر روی پلیر ظاهر می‌شود. برای هر ویدئو می‌توان چند زیرنویس (تا ۱۶ ترک) آپلود، تغییر نام، تعیین پیش‌فرض و حذف کرد.
- **آپلود:** SRT یا VTT (UTF-8، سقف ۲MB). SRT خودکار به WebVTT تبدیل می‌شود (کاما→نقطه در میلی‌ثانیه، BOM/CRLF). زبان و برچسب از نام فایل حدس زده می‌شود (`movie.fa.srt` → برچسب «movie»، زبان fa). فایل `.srt`/`.vtt` را از نوار زیرنویس زیر ویدئو انتخاب کنید.
- **امنیت:** متن cue ها sanitize می‌شود — فقط تگ‌های مجاز VTT (i/b/u/v/c/ruby/rt/rp) می‌مانند؛ `<script>` و هر تگ دیگر escape می‌شود (XSS از طریق فایل زیرنویس بسته است). سرو کردن زیرنویس از همان مسیر احراز هویت مدیا می‌گذرد (کوکی نشست / کلید / لینک امضاشده / پسورد) — زیرنویس ویدئوی محافظت‌شده بدون دسترسی به خود ویدئو قابل خواندن نیست.
- **API:** عمومی `GET /f/{id}/subs` و `GET /f/{id}/subs/{tid}`؛ ادمین `GET/POST /api/v1/admin/objects/{id}/subs`، `PATCH/DELETE /api/v1/admin/objects/{id}/subs/{tid}` (کلیدهای مجاز PATCH: label/lang/default) + audit log.
- **چرخه عمر:** زیرنویس‌ها متادیتای ویدئو هستند (kv `subs:{obj_id}`) — با حذف کامل ویدئو (purge) حذف می‌شوند؛ در لیست فایل‌ها به‌عنوان فایل جدا ظاهر نمی‌شوند.
- **UI:** نوار زیرنویس زیر پلیر در مودال: کلیک روی چیپ = پیش‌فرض‌کردن (★)، دابل‌کلیک = تغییر نام، ✕ = حذف (با تأیید قرمز)، «＋ زیرنویس» = آپلود فایل. توست‌های i18n (fa/en).
- **تست:** ۸ تست جدید (`tests/test_subtitles.py`) — تبدیل/Sanitize، meta نام فایل، lifecycle کامل، جابجایی default، سقف ترک، auth matrix، حذف با purge. کل مجموعه ۳۹۴ سبز.

### محدودیت فعلی
- صفحه آلبوم عمومی (`/a/{token}`) هنوز زیرنویس سرو نمی‌کند — اگر خواستی، فاز بعد اضافه می‌شود.

## v0.15.38 — 2026-09-01

### B-041 (CRITICAL) · دکمه «ابطال همه» اصلاً کار نمی‌کرد
- علت: در v0.15.37 متغیر `liveLinks` داخل `openLinks()` با `let` تعریف شده بود ولی هندلر کلیک دکمه در scope بیرونی به آن ارجاع می‌داد → `ReferenceError: liveLinks is not defined` هنگام کلیک؛ دکمه هیچ کاری نمی‌کرد (نه دیالوگ، نه پیام).
- فیکس: متغیر ماژول‌سطح `linksLiveCount` اضافه شد؛ `openLinks()` بعد از هر load آن را sync می‌کند و هندلر از همان می‌خواند.
- ضمناً هندلر با `guardBtn` پوشیده شد (ضد double-click، هم‌راستا با بقیه دکمه‌های مخرب).

### UX-18 · جای دکمه «ابطال همه» → پایین پنل لینک‌ها
- قبلاً در هدر کنار عنوان بود (کوچک و گم‌شونده)؛ حالا در فوتر کنار «بستن» قرار گرفت — دقیقاً مثل «خالی کردن سطل» در سطل بازیافت (btn-warn، هم‌سایز).

## v0.15.37 — 2026-09-01 (کش از تنظیمات + ری‌استارت همیشگی + گارد ابطال همه)

### FEAT-01 · کلید روشن/خاموش کش دانلود در تنظیمات — بدون .env و ری‌استارت
- قبلاً مسترِ سوئیچ کش فقط `ANBAR_CACHE_ENABLED` در .env بود → دستکاری دستی + ری‌استارت.
- حالا: `cache_enabled` تنظیم runtime شد (runtime.SPEC: 0/1)؛ سوییچ «وضعیت کش دانلود» در تنظیمات آن را زنده سوییچ می‌کند (`_sync_cache` فوری rebuild/teardown می‌کند)، kv ذخیره می‌شود و بعد از ری‌استارت هم می‌ماند (boot path `_build_cache` اورراید را می‌خواند). default = همان .env قبلی؛ رفتار قدیمی بدون اورراید دست‌نخورده.
- ردیف `.env` راهنما حذف شد؛ وقتی خاموش است فقط بودجه/پاک‌سازی غیرفعال می‌شوند.

### UX-15 · دکمه «⟳ ری‌استارت» همیشه در فوتر تنظیمات دیده می‌شود
- قبلاً فقط بعد از ذخیره‌ی یک کلیدِ وابسته به ری‌استارت ظاهر می‌شد (markDirty). حالا ثابت است؛ بعد از ری‌استارت هم مخفی نمی‌شود.

### UX-16 · «ابطال همه» بدون لینک فعال → پیام به‌جای توست بی‌معنی
- وقتی هیچ لینک زنده‌ای نیست: toast «هیچ لینک فعالی وجود ندارد — چیزی برای ابطال نیست» و هیچ دیالوگی باز نمی‌شود.

### UX-17 · تأیید «ابطال همه» حالا قرمز (danger) است
- دیالوگ تأیید با `{danger:true}` باز می‌شود (هم‌راستا با خالی‌کردن سطل و ری‌استارت). توست موفقیت تعداد لینک‌های باطل‌شده را هم نشان می‌دهد: «… باطل شدند (N)».

## v0.15.36 — 2026-09-01 (ادامه سشن قبلی: ابطال همه + لیبل آلبوم پوشه + توضیح کش)

### B-038 · دکمه «ابطال همه» لینک‌های آلبوم را باطل نمی‌کرد — Severity: HIGH
- «ابطال همه» فقط ردیف‌های `link:*` را حذف/تومبستون می‌کرد؛ آلبوم‌ها در kv جداگانه (`album:*`) هستند و صفحه‌ی `/f/a/<token>` را زنده نگه می‌داشتند → توست موفقیت، ولی لینک پوشه همچنان کار می‌کرد.
- فیکس: `revoke_all()` حالا همه‌ی ردیف‌های `album:*` را هم حذف می‌کند (صفحه آلبوم همان‌جا 404 می‌شود). تست: `test_revoke_all_kills_albums_too` — قبل 404 نمی‌شد، حالا هر دو آلبوم 404 ✅

### B-039 · ردیف آلبوم پوشه، اسم همه فایل‌ها را نشان می‌داد — Severity: MEDIUM
- لیبل آلبومِ پوشه‌ای «a.png / b.png / c.png …» بود. حالا فقط اسم پوشه (مادر-ترین پوشه مشترک؛ حتی با زیرپوشه‌های تودرتو): `myfolder` — چند پوشه: `alfa / beta` — فایل‌های بی‌پوشه: مثل قبل.
- باگ سشن قبل: فیلترِ «پوشه سطح بالا» وارونه بود (`o.startswith(d+"/")` به‌جای `d.startswith(o+"/")`) → لیبل `myfolder/deep` به‌جای `myfolder`. فیکس + تست‌های تک‌پوشه/چندپوشه/بدون‌پوشه ✅

### DOC-02 · ردیف «حالا» در بخش کش دانلود مبهم بود — Severity: LOW
- «حالا» در واقع «فضای فعلاً پرشده از کش» بود (bytes/entries زنده از /admin/cache/info) — نه عملیاتی. لیبل → «فضای پرشده از کش» با نمایش `X / Y MB · N obj`؛ ساب‌تکست max حجم هم توضیح کامل‌تر گرفت (LRU · ۰ = غیرفعال). EN: "Cache used".

### B-040 · پس از دیپلوی، سرور crash-loop شد: `ANBAR_CHANNEL_THREAD_ID=` خالی — Severity: CRITICAL (runtime)
- Settings UI مقدار خالی را به‌صورت `ANBAR_CHANNEL_THREAD_ID=` در .env می‌نویسد؛ pydantic-settings رشته‌ی خالی را برای `int | None` parse نمی‌کند → کل اپ در استارتاپ می‌مرد (ValidationError: int_parsing input='').
- فیکس در کد (نه دستکاری .env): `env_ignore_empty=True` در SettingsConfigDict — مقدار خالیِ env یعنی «unset» و به default می‌رود. رگرسیون: `tests/test_v01536_empty_int_env.py` (خالی → None، ۷۷۷ → ۷۷۷) ✅

## v0.15.35 — 2026-09-01 (۹ اصلاح UI/UX)

### B-035 · مودال اشتراک/تغییرنام زیر کارت گالری باز می‌شد — Severity: HIGH
- کارتی که منوی ۳نقطه‌اش باز بود `.menu-open` (z-index:999) می‌گیرد؛ مودال‌ها z-index:150 داشتند → مودال زیر کارت رندر می‌شد. فیکس: z-index مودال‌ها ۱۲۰۰ + پاک‌کردن `.menu-open` هنگام باز شدن هر مودال/دیالوگ (openShareOpts / askText / askConfirm). E2E: modalZ=1200، menuOpenStuck=false ✅

### B-036 · لینک‌های آلبوم (اشتراک پوشه) در «لینک‌های فعال» نمایش داده نمی‌شدند — Severity: HIGH
- آلبوم‌ها در kv جداگانه (album:*) بودند و هرگز در رجیستری link:* ثبت نمی‌شدند. `list_albums()` اضافه شد و `GET /admin/links` آلبوم‌های زنده را با برچسب 🖼 و مسیر /f/a/<token> ادغام می‌کند. ابطال آلبوم: `POST /admin/album/<token>/revoke` (جدید). E2E: ۲۳ ردیف آلبوم در پنل ✅

### B-037 · صفحه آلبوم عمومی فارسی/RTL بود — Severity: MEDIUM
- طبق درخواست: صفحه‌ی `/f/a/<token>` کاملاً انگلیسی شد (lang="en"، بدون RTL؛ Download/View/files·anbar؛ پیام‌های 404/410 هم انگلیسی). E2E: en=true, rtl=false, fa=false ✅

### UX-09 · تیک سبز «لاگین تلگرام فعال است» در زبان انگلیسی کشیده می‌شد — Severity: LOW
- دایره‌ی ✓ در flex با متنِ بلندتر EN له می‌شد (22×32). فیکس: `min-width:32px;flex:none;line-height:1`. E2E: 32×32 ✅

### UX-10 · پوشه‌ی خالی در نمای گالری، نمای لیستی می‌گرفت — Severity: MEDIUM
- `#noMatch` بیرون از کانتینر گالری رندر می‌شد و ظاهر جدول برمی‌گشت. حالا در حالت گالری خودش `.gallery` می‌گیرد (تیغه‌ی شفاف، هدر جدول مخفی). E2E: galleryChrome=true, theadHidden=true ✅

### UX-11 · «خالی کردن سطل» روی سطل خالی بی‌معنی بود — Severity: LOW
- سطل خالی → توست «سطل زباله خالی است — چیزی برای خالی کردن نیست» بدون دیالوگ. E2E ✅

### UX-12 · تأیید خالی‌کردن سطل، رنگ قرمز نداشت — Severity: LOW
- `askConfirm(text,{danger:true})` → دکمه‌ی تأیید قرمز (rgb(220,38,38)) برای عمل مخرب. E2E ✅

### UX-13 · متن «اعمال بعد از ذخیره + ری‌استارت» ولی هیچ ری‌استارتی وجود نداشت — Severity: MEDIUM
- `POST /admin/restart` اضافه شد (SIGTERM تمیز؛ کانتینر با restart policy بالا می‌آید) + دکمه‌ی «⟳ ری‌استارت» در فوتر drawer که فقط وقتی یکی از کلیدهای .env-محور (backend، توکن‌ها، کانال، api id/hash، chunk size) تغییر کند ظاهر می‌شود؛ بعد از ری‌استارت healthz را poll می‌کند و UI را رفرش می‌کند.

### UX-14 · سایر تنظیمات نیازمند ری‌استارت مشخص نبودند — Severity: LOW
- ورودی‌های .env-محور `data-dirty-key` گرفتند؛ هر تغییری (تایپ یا ذخیره) دکمه‌ی ری‌استارت را نشان می‌دهد. کلیدهای runtime (نرخ‌ها، کش، TTL، نمای پیش‌فرض…) نیازی به ری‌استارت ندارند و دکمه را نشان نمی‌دهند.

- **تست:** ۳ تست جدید (`tests/test_v01535_albums_ux.py`) + به‌روزرسانی تست 404 آلبوم به انگلیسی. سوئیت: 373 → **376 passed**.

## v0.15.34 — 2026-09-01 (سه تغییر UX طبق درخواست)

### UX-06 · حذف دکمه‌ی «آپلود پوشه» از تولبار — Severity: TRIVIAL
- دکمه در بخش آپلود تکراری بود (کشیدن پوشه روی dropzone + راست‌کلیک/لمس طولانی همان کار را می‌کند). از تولبار حذف شد؛ `dirInput` و مسیر راست‌کلیک دست‌نخورده ماند.

### UX-07 · دکمه‌ی «لغو» وسط ردیف آپلود — Severity: TRIVIAL
- قبلاً با `margin-left:auto` به انتهای ردیف چسبیده بود؛ حالا به‌عنوان فرزند میانی `.qstat` (flex space-between) **وسط** ردیف می‌نشیند: وضعیت ← لغو ← درصد. هندسه در مرورگر واقعی تأیید شد (مرکز دکمه 387 ≈ مرکز ردیف 385).

### UX-08 · حذف جمله‌ی توضیحی توکن‌ها از تنظیمات — Severity: TRIVIAL
- متن «هر توکن جداگانه اضافه/حذف می‌شود (برای چرخش و افزایش سرعت) — نیازی به جداکردن با کاما نیست.» از زیر فیلد توکن‌های بات حذف شد؛ فقط «اعمال بعد از ذخیره + ری‌استارت.» باقی ماند (FA + EN).

## v0.15.33 — 2026-09-01 (زیپ/اشتراک پوشه‌ی جدید «همان ارورهای قبلی» — کش کهنه‌ی کلاینت)

### B-034 · پوشه‌ی تازه‌پرشده zip و share نمی‌شد («اشتراک گروهی/دانلود زیپ فقط برای فایل هاست») — Severity: HIGH
- **باس:** `downloadFolderZip` و `shareFolder` لیست idها را از آرایه‌ی **`files[]` سمت کلاینت** می‌گرفتند (حداکثر ۵۰۰ ردیف، فقط بعد از refresh به‌روز می‌شود). اگر فایل تازه داخل پوشه آپلود شده بود — مخصوصاً از تب/دستگاه دیگر یا بدون صبر برای refresh — این کش از وجود آن‌ها بی‌خبر بود → `collectFolderIds()` خالی برمی‌گشت → توست گمراه‌کننده‌ی «فقط برای فایل‌هاست». به همین دلیل «فقط همان پوشه‌ی نمونه درست بود» — چون در همان سشن refresh شده بود.
- **ریشه‌یابی:** E2E مرورگر واقعی نشان داد پوشه‌ی جدیدی که با فایل آپلودشده داخلش ساخته شد (Htest2) zip → 200 `application/zip` و share → لینک آلبوم معتبر می‌دهد. سناریوی شکست فقط وقتی است که کش کلاینت stale باشد.
- **فیکس (دو لایه):**
  1. `GET /api/v1/admin/objects?prefix=<p>` — فیلتر سمت سرور (authoritative) با `list_objects_by_prefix`؛ marker خود پوشه حذف می‌شود.
  2. UI: `serverFolderIds()` — زیپ و اشتراک پوشه همیشه idهای تازه را از سرور می‌گیرند؛ فقط اگر API شکست بخورد به کش محلی fallback می‌شود. `shareFolder` دیگر با توست pre-block نمی‌کند.
- **تست:** `tests/test_v01533_folder_ids.py` — ۳ تست (prefix filter، حذف marker، سازگاری با حالت بدون prefix). سوئیت: 370 → **373 passed**.
- **E2E پروداکشن v0.15.33:** آپلود مخفی به Kkkk (کش متوجه نمی‌شود) → zip → لینک آلبوم `…/f/a/kewwif7ds3gw` → صفحه آلبوم **۲ فایل** رندر شد ✅

## v0.15.32 — 2026-09-01 (گالری آلبوم خالی رندر می‌شد + ترتیب اکشن‌های کارت پوشه)

### B-033 · صفحه اشتراک پوشه (آلبوم) هیچ فایلی نشان نمی‌داد — Severity: HIGH
- **باس:** در اسکریپت گالری آلبوم `/f/a/<token>` نوشته شده بود `const ITEMS = JSON.parse(__PAYLOAD__)` در حالی که payload به‌صورت **آرایه‌ی JSON خام** (خروجی `json.dumps`، بدون کوتیشن) جایگذاری می‌شد. `JSON.parse([{...}])` یک SyntaxError می‌دهد → کل `<script>` صفحه می‌مرد → `#grid` خالی می‌ماند. سرور همه‌چیز را درست می‌فرستاد («2 فایل» در هدر صفحه درست بود) اما مرورگر هیچ سلولی رندر نمی‌کرد. تأیید: `rows:[]` و `grid children:0` در مرورگر واقعی با payload سالم.
- **فیکس:** جایگذاری مستقیم `const ITEMS = __PAYLOAD__;` (آرایه‌ی literal). خروجی `json.dumps` با `</` escape شده و نام‌ها هم server-side HTML-escaped هستند (فیکس XSS قبلی v0.15.14 دست‌نخورده).
- **تست:** `tests/test_v01532_album_payload.py` — ۲ تست (حذف wrapper خراب + صحت ساختار ITEMS: id/name/sig). E2E مرورگر واقعی روی لینک آلبوم کاربر: ۲ سلول رندر شد، دانلود anonymous با لینک امضاشده **200**. سوئیت: 368 → **370 passed**.

### UX-05 · ترتیب اکشن‌های کارت پوشه مثل کارت فایل شد — Severity: TRIVIAL
- **باس:** ترتیب دکمه‌های پوشه (zip، share، rename، move، copy، del) با ترتیب فایل‌ها (dl، share، copy، rename، move، del) فرق داشت — copy بین rename و move بود.
- **فیکس:** در هر دو نمای list و gallery ترتیب پوشه به zip | share | **copy** | rename | move | del تغییر کرد تا با ترتیب فایل‌ها یکی شود.


## v0.15.31 — 2026-09-01 (ریشه واقعی «پریویو/دانلود کار نمی‌کند»: مرگ کوکی سشن + lazy-load deadlock)

### B-031 · مرگ کوکی سشن → کل UI بی‌اعتبار می‌شد (ریشه اصلی گزارش «پریویو نمی‌آید، دانلود fail می‌شود») — Severity: HIGH
- **باس:** `boot()` وضعیت لاگین را با `api("/ui/me")` می‌سنجید؛ `/ui/me` علاوه بر کوکی، هدر `Authorization: Bearer` (از localStorage) را هم می‌پذیرد. پس بعد از انقضای کوکی سشن، UI «لاگین‌شده» می‌ماند در حالی که **هیچ** `<img>/<video>/<a download>` کار نمی‌کرد — چون این المان‌ها هدر Bearer نمی‌فرستند و فقط به کوکی تکیه دارند → همه‌ی URLهای بدون‌کلید 401 می‌گرفتند. این همان چیزی بود که لینک `https://dl.amiri-dev.ir/f/kDjYsQ5EHR2s` را برای کاربر «خراب» نشان می‌داد.
- **فیکس:** در `boot()` وابستگی به `/ui/me` حذف شد؛ الان **همیشه** با کلید ذخیره‌شده در localStorage یک `POST /ui/login` خاموش می‌زند تا کوکی تازه ضرب شود، بعد `/ui/me` را چک می‌کند. اگر کلید نامعتبر بود → فرم لاگین. نتیجه: مرگ کوکی دیگر برای کاربر نامرئی است — reload کافی است.
- **تست:** `tests/test_v01531_boot_cookie.py` — ۳ تست: (۱) مدیای بی‌کوکی 401 حتی بدون Bearer، (۲) login کوکی می‌سازد که مدیای بدون کلید را 200 می‌کند، (۳) سناریوی دقیق کاربر: لاگین → پاک‌شدن کوکی → مدیا 401 → re-login → مدیا 200. سوئیت: 365 → **368 passed**.

### B-032 · `loading="lazy"` روی تصویر پریویو مودال = deadlock (تصویر هرگز لود نمی‌شود) — Severity: MEDIUM
- **باس:** `<img loading="lazy">` داخل کانتینر flex با `overflow` — تصویر تا قبل از لود، layout box صفر (0×0) دارد؛ lazy-loading با باکس صفر **هرگز fetch نمی‌شود** → spinner ابدی. تأیید آزمایشگاهی: همان URL با `new Image()` بیرون از مودال فوراً لود می‌شد (naturalHeight=8) اما `<img>` داخل مودال در 0×0 می‌ماند.
- **فیکس:** حذف `loading="lazy"` از تصویر پریویو مودال (`src/anbar/ui/index.html`) — پریویو eager لود می‌شود؛ گالری که باکس واقعی دارد lazy می‌ماند.
- **تست:** E2E مرورگر واقعی: بعد از فیکس، `complete=true` و `naturalHeight=8` داخل مودال.

### نکته درباره ویدیو (پیدا شد در تحقیق، باگ نیست)
- فایل mp4 نمونه‌ی کاربر (jumb-box iPhone-style، moov در انتهای فایل) در headless-Chromium این تست demux نمی‌شود (`readyState=0` حتی با blob-src)؛ اما لایه‌ی HTTP سالم است: range ها همگی 206 و سریع (8ms برای 1MB میانی). در Firefox/Chrome واقعی باید decode شود. اگر در مرورگر واقعی هم پریویوی ویدیو نچرخد، گزارش بده تا moov-ری‌رایت یا transcode اضافه شود.

## v0.15.30 — 2026-09-01 (اصلاح فیکس اشتباه v0.15.29 — SEC-02 سر جایش، UI بدون کلید)

### FIX-06 · بازگردانی فیکس نادرست v0.15.29 — Severity: Critical/Security — ✅ درست شد
- **اشتباه من:** در v0.15.29 به‌جای اصلاح UI، پذیرش کلید ادمین در `?k=` را برگرداندم — یعنی کل فیکس امنیتی SEC-02 (تمام تلاش v0.15.20) را دور زدم. کاربر درست تذکر داد.
- **تحلیل درست ریشه:** دکمه‌ی دانلود UI لینک را به شکل `/f/<id>?k=<کلید ادمین>` می‌ساخت (این لینکِ دست‌نخورده از v0.15.20 ماند). بعد از SEC-02 این لینک‌ها 401 می‌دادند → «هیچ پریویویی نیست و هیچ فایلی دانلود نمی‌شود». پریویوها هم از همان mediaUrl استفاده می‌کردند.
- **فیکس درست (ui/index.html):**
  - `mediaUrl(o)`: دیگر هیچ کلیدی در URL نمی‌گذارد → `/f/<id>` خالص. درخواست‌های `<img>/<video>/<audio>/<iframe>` و anchor دانلود same-origin هستند و کوکی سشن را حمل می‌کنند → مجاز.
  - thumb گالری: `?k=` حذف شد (همان دلیل).
  - silent re-login (v0.15.28) کوکی مرده را شفاف تازه می‌کند، پس پریویو/دانلود بدون هیچ کلیدی در URL همیشه کار می‌کند.
- **SEC-02 بازگشت به سر جای قبلی (api/download.py):** کلید ادمین در `?k=` دوباره 401. فقط کلید آپلودر/API و dynamic keyها در URL مجازند.
- **Verify (E2E مرورگر واقعی روی پروداکشن):**
  - URL کاربر با کلید ادمین → **401** (SEC-02 برقرار) ✓
  - دانلود از UI → href = `https://dl.amiri-dev.ir/f/kDjYsQ5EHR2s` (بدون کلید) → **200** ✓
  - پریویو تصویر (Image onload, naturalHeight=8) ✓ · پریویو متن ✓ · thumb گالری keyless → 200 ✓
  - لینک اشتراک (دکمه‌ی کپی) → `?sig=…&exp=…` امضاشده → دانلود anonymous **200** ✓ (اشتراک عمومی همچنان از مسیر امضا، هرگز با کلید ادمین)
  - کلید ادمین در هیچ‌جای DOM رندرشده نیست (`document.body.innerHTML` بررسی شد) ✓
  - تست جدید: admin key در `?k=` → 401؛ همان درخواست با کوکی سشن → 200. سوئیت کامل **365 passed** ✓

## v0.15.29 — 2026-09-01 (هات‌فیکس — ❌ فیکس اشتباه، در v0.15.30 اصلاح شد)

### FIX-05 (باطل‌شده) · بازگرداندن پذیرش کلید ادمین در ?k= — ❌ WRONG
- لینک دقیق کاربر 200 شد ولی این یعنی دورزدن SEC-02 — کلید ادمین دوباره در لاگ/referrer/history لو می‌رفت. **در v0.15.30 معکوس شد**؛ ریشه‌ی واقعی (UI که کلید در URL می‌گذاشت) همان‌جا درست شد. این ورودی فقط برای ثبت تاریخچه است.

## v0.15.28 — 2026-09-01 (Session Continuation — 4 reported bugs + 1 verified-OK)

### FIX-01 · لرزش/جابه‌جایی دکمه لغو آپلود — Severity: UI — ✅ فیکس شد
- **باس:** در حین آپلود، دکمه «لغو» با هر تغییر درصد، چپ‌وراست می‌شد. علت: `.qstat` با `justify-content:space-between` سه فرزند داشت (وضعیت، دکمه لغو، درصد)؛ متن درصد (`12%` → `100%`) عرض فرزند وسط را تغییر می‌داد و دکمه را می‌لغزاند. (E2E قبلی: نوسان ~1.4px اندازه‌گیری شد.)
- **فیکس (ui/index.html):**
  - درصد به span با عرض ثابت `.qstat .qpct` (min-width:34px + tabular-nums) منتقل شد.
  - دکمه لغو با `margin-left:auto` به انتهای ردیف قفل شد.
- **Verify (E2E مرورگر واقعی، آپلود 40MB روی پروداکشن):** ۸ نمونه‌برداری متوالی از `getBoundingClientRect` دکمه → `x=646.7, right=683.9` **ثابت مطلق** (تغییر صفر پیکسل) در حالی که درصد 65→100 می‌رفت ✓. رنگ قرمز `rgb(220,38,38)` حفظ شد ✓.

### FIX-02 · متن قدیمی «با کاما جدا کنید» در توضیح توکن‌های بات — Severity: UX — ✅ فیکس شد
- **باس:** از v0.15.26b توکن‌ها یکی‌یکی اضافه/حذف می‌شوند، ولی کلید i18n `tgTokensSub` (fa و en) هنوز متن قدیمی «چند توکن را با کاما جدا کنید» را داشت و placeholder نیز لیست masked را با کاما نشان می‌داد.
- **فیکس (ui/index.html):** متن fa/en هر دو به «هر توکن جداگانه اضافه/حذف می‌شود (برای چرخش و افزایش سرعت) — نیازی به جداکردن با کاما نیست» تغییر کرد؛ placeholder کاما-جذو حذف شد (پلاین `123456:ABC-DEF...`).
- **Verify (E2E):** متن رندرشده در drawer تنظیمات با `applyI18n` = متن جدید ✓.

### FIX-03 · API Hash همیشه نقطه‌ای — Severity: UX — ✅ فیکس شد (reveal واقعی)
- **باس:** فیکس v0.15.26 فقط مقدار **masked** را نشان می‌داد (مثل `2ddb••••2ffb`)؛ کاربر انتظار هش واقعی را داشت. B-054 هش خام را از پاسخ listing حذف کرده بود (درست)، پس toggle چیزی برای نمایش نداشت.
- **فیکس:**
  - `GET /api/v1/admin/telegram-config/reveal-api-hash` (جدید در api/admin.py): هش خام را فقط به ادمین می‌دهد، هر کلیک با `cfg.reveal_api_hash` audit می‌شود.
  - UI: toggle حالا endpoint را صدا می‌زند و مقدار واقعی را در فیلد (type=text) می‌گذارد؛ hide دوباره خالی می‌کند. هش تایپ‌شده‌ی ذخیره‌نشده حفظ می‌شود؛ ذخیره‌ی مقدار masked همچنان سمت سرور رد می‌شود (بدون ریسک بازنویسی).
- **Verify (E2E پروداکشن):** reveal → طول ۳۲ کاراکتر بدون `•` ✓؛ hide → فیلد خالی + type=password ✓؛ بدون کوکی/کلید ادمین → 401 ✓؛ کلید اشتباه → 401 ✓؛ audit row ثبت شد ✓؛ تست‌های unit جدید (۴ تست) ✓؛ تست B-054 قبلی (mask در listing) همچنان پاس ✓.

### FIX-04 · خراب‌بودن پریویو و دانلود — Severity: Critical — ✅ ریشه‌یابی + فیکس
- **ریشه:** SEC-02 (v0.15.20) پذیرش **کلید ادمین** در `?k=` را از `_authenticate_download` حذف کرد (درست، ضد leaked-URL)؛ ولی UI همچنان همه‌ی `<img>/<video>/<audio>/<iframe>` و لینک دانلود را به شکل `/f/<id>?k=<ADMIN_KEY>` می‌سازد. تا وقتی کوکی سشن زنده است، `whoami` از کوکی admin برمی‌گردد و همه‌چیز کار می‌کند؛ به محض **انقضای کوکی سشن** (پیش‌فرض چند روزه)، Bearer در localStorage هنوز برای `/api/*` جواب می‌دهد ولی هر درخواست پریویو/دانلود **401** می‌خورد → «پریویو خراب، دانلود fail». (این نتیجه‌ی بازتولید مسیر دقیق 401 است؛ خود E2E با کوکی تازه 200 می‌گرفت.)
- **فیکس (ui/index.html):**
  - `boot()`: اگر کوکی مرده ولی کلید در localStorage هست، یک‌بار **silent re-login** (`POST /ui/login`) می‌زند و سشن تازه می‌سازد — دیگر کاربر به صفحه لاگین پرت نمی‌شود و کلیدش پاک نمی‌شود.
  - `api()`: روی 401 یک‌باره silent re-login تلاش می‌کند (درخواست‌های GET؛ یک‌بار در هر سشن) تا URLهای media دوباره زنده شوند.
  - (`?k=` با کلید ادمین عمداً دست‌نخورده ماند — رفع کامل آن نیازمند endpoint امضاشده per-preview است؛ ثبت شد برای نسخه بعد. با re-login خودکار، از دید کاربر دیگر crash دیده نمی‌شود.)
- **Verify (E2E پروداکشن):** پریویو text (محتوای درست) ✓؛ پریویو PNG (`complete && naturalHeight>0`) ✓؛ دانلود `/f/<id>?k=...` → 200 ✓؛ لاگین مجدد silent → `/ui/me` = `authed:true` ✓.

### VERIFY-OK · ZIP و اشتراک پوشه (عنوان گزارش «هنوز خراب») — ✅ سالم بود
- **E2E مرورگر واقعی روی پروداکشن:** دکمه ZIP ردیف پوشه → `POST /f/zip` → **200** با blob معتبر (700KB) ✓؛ دکمه اشتراک پوشه → مودال گزینه‌ها با `shareTarget="folder:e2e UX folder/"` → آلبوم عمومی `…/f/a/<slug>` با «انقضا: 1d» و صفحه آلبوم 200 برای anonymous ✓. دکمه ۲۴ ساعته همان option پیش‌فرض `24 hours` مودال اشتراک است و TTL آلبوم per-item را از v0.15.27 درست ست می‌کند.
- نشان «دانلود زیپ فقط برای فایل‌هاست» فقط برای پوشه‌های **خالی** ظاهر می‌شود (`collectFolderIds` خالی) — پیام‌های اختصاصی «پوشه خالی است» اضافه شد تا گمراه‌کننده نباشد.

### تست‌ها
- `tests/test_v01528_hash_reveal.py` (جدید، ۴ تست): reveal خام برای ادمین، 401 برای anon/uploader، audit-log، ماندگاری mask در listing.
- کل سوئیت: **364 passed** — ruff روی فایل‌های تغییرکرده clean (13 error از قبل در scripts/ بود) — deploy واقعی روی dl.amiri-dev.ir (v0.15.28).

## v0.15.27 — 2026-08-31 (E2E Verification Follow-up — 5 reported bugs)

### FIX-01 · دکمه لغو آپلود قرمز نشده بود — Severity: UI (رگرسیون v0.15.26)
- **باس:** فیکس UX-01 برای دکمه لغو (`.qcancel`) رنگ قرمز داشت، ولی selector تک‌کلاسه `.qcancel` با specificity برابرِ `.btn-ghost` (خط 184، بعداً در فایل) در جنگ cascade می‌باخت؛ رنگ و border دوباره خاکستری می‌شد (`rgb(90,101,120)` اندازه‌گیری شد در E2E).
- **فیکس (ui/index.html):** selector به `.qcancel.btn` (specificity 0,2,0) ارتقا یافت تا از `.btn-ghost` (0,1,0) بالاتر باشد. hover هم اصلاح شد.
- **Verify (E2E واقعی):** رنگ computed دکمه = `rgb(220,38,38)` = `--err` ✓؛ کلیک → state `canceled` + `xhr.abort` ✓.

### FIX-02 · ذخیره‌نشدن تنظیمات/توکن‌ها در پروداکشن — Severity: Critical
- **باس:** در پروداکشن `/opt/anbar/.env` یک فایل bind-mount تک‌فایلی داخل دایرکتوری root-owned است؛ مسیر atomic نوشتن (mkstemp در همان دایرکتوری + `os.replace`) با **EACCES** (ساخت temp در دایرکتوری 755 روت) و سپس **EBUSY** (rename روی bind-mount) شکست می‌خورد. `_write_env_dict` ساکت `False` برمی‌گرداند ولی endpoint همچنان `{"status":"ok","updated_keys":[...]}` می‌داد → UI «ذخیره شد» نشان می‌داد، تغییرات بعد از restart پرت می‌شدند. (لاگ: هر توکن اضافه‌شده از UI عملاً هیچ‌وقت persist نمی‌شد.)
- **فیکس (api/admin.py):**
  - `_write_env_dict`: مسیر atomic حفظ شد (SEC-04)؛ در failure به fallback **in-place rewrite** (O_TRUNC + write + fsync + بکاپ .bak) می‌رود که روی bind-mount کار می‌کند. اگر آن هم شکست بخورد `False` برمی‌گردد.
  - `POST /admin/telegram-config`: وقتی persist شکست می‌خورد حالا **HTTP 500** برمی‌گرداند (قبلاً ok دروغین). پاسخ موفق شامل `persisted: true` است.
- **Verify (E2E پروداکشن):** افزودن توکن تستی → `persisted:true` + شمارش 3 + کلید واقعاً در `/opt/anbar/.env` روی host ظاهر شد ✓؛ حذف همان توکن → شمارش 2 و کلید از فایل پاک شد ✓؛ index خارج از محدوده → 404 ✓؛ تست unit جدید نوشتن روی .env شبه-bind-mount (EBUSY+دایرکتوری غیرقابل‌نوشتن) ✓.

### FIX-03 · چشمک API Hash (نمایش/مخفی) — Severity: UX — ✅ سالم بود
- **بررسی E2E:** دکمه `s_tg_hash_toggle` موجود و سیم‌کشی‌شده است؛ `password → text → password` به‌درستی toggle می‌شود (سه اسنپ‌شات computed type). باگ گزارش‌شده بازتولید نشد — احتمالاً اثر بصریِ خالی‌بودن مقدار (وقتی hash ذخیره نشده، input خالی است و toggle دیده نمی‌شود که «کاری کرد»). بدون تغییر کد.

### FIX-04 · لیست توکن‌های ربات + شمارنده — Severity: UX — ✅ سالم بود + باگ ریشه‌ای FIX-02
- **بررسی E2E:** لیست `#tgTokensList` با ردیف masked + دکمه حذف هر توکن رندر می‌شود؛ شمارنده `(N active)` زنده آپدیت می‌شود (2→3→2 در add/remove واقعی UI). textarea قدیمی حذف شده و input «افزودن تکی» کار می‌کند.
- **اما ریشه «ثبت نشدن»:** همان FIX-02 بود — توکن به لیست UI اضافه می‌شد ولی persist ساکت شکست می‌خورد. الان واقعاً در `.env` می‌نشیند.

### FIX-05 · تیک تکراری select-mode — Severity: UI — ✅ سالم بود
- **بررسی E2E:** قانون `.gcell.selected::after` (منبع تیک دوبل) دیگر در هیچ stylesheet وجود ندارد (`False`)؛ انتخاب واقعی یک فایل در گالری → فقط یک checkbox تیک می‌خورد و هیچ badge ::after روی کارت انتخاب‌شده رندر نمی‌شود (badges = `[]`).

### FIX-06 · انقضای لینک آلبوم/پوشه — Severity: Medium (رگرسیون v0.15.26b)
- **باس:** آلبوم‌های ساخته‌شده از اشتراک پوشه `ttl` را نادیده می‌گرفتند: توکن آلبوم با ttl درست ذخیره می‌شد ولی `exp` per-item ها همیشه `now + 30d` (امضای قدیمی) بود؛ صفحه آلبوم بعد از 30 روز لینک‌های مرده می‌داد در حالی که توکن زنده بود (یا برعکس با ttl=0 امضا نمی‌شد).
- **فیکس (api/download.py):** `exp` per-item = `now + ttl` (0 = هرگز)؛ آلبوم منقضی → **410 Gone** با پیام فارسی؛ 404 برای توکن ناموجود حفظ شد.
- **Verify (E2E پروداکشن):** اشتراک پوشه «e2e UX folder» با ttl=86400 → صفحه آلبوم 200 با 2 آیتم، هر دو `exp ≈ 24h` ✓ (قبلاً 30d ثابت)؛ تست‌های unit: default 24h، ttl=0 (>30d)، ttl=600، منقضی→410 ✓.

### تست‌ها
- `tests/test_v01527_fixes.py` (جدید، ۹ تست): fallback بنویس on-bind-mount، افزودن کلید جدید، endpoint fail-loud 500، endpoint ok با fallback، add-token flow، آلبوم ttl پیش‌فرض/صفر/سفارشی/منقضی.
- کل سوئیت: **360 passed** — ruff clean — deploy واقعی روی dl.amiri-dev.ir (v0.15.27 @ c132f6d).

## v0.15.26 — 2026-08-31 (UX Fixes — گزارش کاربر)

### UX-01 · دکمه لغو آپلود — Severity: UX
- **باس:** صف آپلود فقط دکمه retry برای آیتم‌های fail داشت؛ در حین آپلود (حتی چندصد مگابایتی) هیچ راهی برای پشیمانی و لغو نبود.
- **فیکس (src/anbar/ui/index.html):**
  - دکمه «لغو» روی هر آیتم در حالت `wait` (در صف) و `up` (در حال ارسال).
  - `uploadOne` هندل XHR را روی آیتم نگه می‌دارد (`it._xhr`)؛ `cancelItem(id)` آن را abort می‌کند (`xhr.onabort` → reject با sentinel `__canceled__`).
  - `pump()` حالت `canceled` را از `fail` تشخیص می‌دهد، آیتم لغوشده بعد از ۴ ثانیه مثل done از صف پاک می‌شود و صف به آیتم بعدی می‌رود.
  - i18n: `tCancel` / `tCanceled` در fa/en.

### UX-02 · ریسپانسیو نبودن صفحه اصلی در desktop — Severity: UI
- **باس:** `.wrap` و `.topbar-in` با `max-width:1080px` هاردکپ شده بودند (میراث mobile-first)؛ روی مانیتورهای عریض صفحه یک نوار باریک وسط می‌ماند و جدول فایل‌ها از کانتینر بیرون می‌زد.
- **فیکس:**
  - عرض سیال `max-width:min(1280px,96vw)` برای هر دو کانتینر.
  - `table{table-layout:fixed}` + نسبت ستون‌ها (نام = auto/باقی‌مانده، حجم/تاریخ/دانلود = 150px، عملیات = 250px) + `overflow:hidden; text-overflow:ellipsis` روی th/td — جدول همیشه در کادر خود جا می‌شود و نام فایل بلند ellipsis می‌گیرد.
  - `@media(max-width:720px)` (حالت کارت) ریست می‌شود: `table-layout:auto` و `th{width:auto !important}`.

### UX-03 · دانلود ZIP و اشتراک کل پوشه — Severity: Feature Gap
- **باس:** endpoint های `/f/zip` و `/f/album` از قبل وجود داشتند (v0.10/v0.10.4) ولی فقط برای multi-select سیم‌کشی شده بودند؛ برای پوشه‌ها هیچ اکشنی نبود.
- **فیکس:**
  - `collectFolderIds(prefix)`: اعضای پوشه از لیست لودشده (≤500 ردیف، همان داده جدول) جمع می‌شود.
  - `downloadFolderZip(prefix)`: ZIP استریمی همه فایل‌های پوشه با نام `anbar-<folder>-<date>.zip`.
  - `shareFolder(prefix)`: یک لینک آلبوم عمومی برای کل پوشه.
  - Table view: دو دکمه جدید ZIP و اشتراک در اکشن‌های ردیف پوشه. Gallery view: دو آیتم در منوی ⋮ پوشه. هندلرها در هر دو view وصل شدند.

### UX-04 · هدر جدول و پس‌زمینه پشت کارت‌های گالری — Severity: UI
- **باس:** `renderGallery` فقط `tbody` را خالی می‌کرد و گرید را داخل `.tbl-wrap` می‌گذاشت؛ قانون CSS فعلی فقط `overflow:visible` می‌داد — پس نوار «نام/حجم/تاریخ/دانلود/عملیات» (thead) و صفحه سفید سایه‌دار کانتینر پشت کارت‌ها می‌ماند.
- **فیکس:** قوانین `:has(.gallery)` کامل شد — `thead{display:none}`، `table{display:none}` و `background:transparent; border:none; box-shadow:none` برای کانتینر. (پیش‌تر باگ UI-04 از IMPROVEMENT_PLAN فقط overflow را هندل کرده بود.)

### UX-05 · المان‌های stale بعد از سوییچ زبان — Severity: i18n
- **باس:** `applyI18n()` فقط `[data-i18n]` را re-render می‌کرد؛ هر متنِ دینامیکِ با `t()` ساخته‌شده تا رفرش بعدی به زبان قبلی می‌ماند. موارد یافت‌شده:
  1. «ZK: خاموش/روشن» بج dropzone (فقط با `syncClientZkUI` آپدیت می‌شد)
  2. صف آپلود (وضعیت‌ها + دکمه retry)
  3. tooltip دکمه table/gallery
  4. دکمه نمایش/پنهان API Hash
  5. دکمه select mode
  6. چیپ‌های مدال فایل (chunks/downloads)
  7. مودال‌های باز Links/Trash
  8. دکمه‌های Preview/Raw پریویو md
  9. کل باکس MTProto Auth (عنوان، توضیح، دکمه‌های ارسال کد/تأیید/خروج) — HTML هاردکد فارسی
  10. toast/confirm های جریان OTP تلگرام (نیاز به شماره، در حال ارسال، …)
- **فیکس:** `applyI18n` حالا همه سطرف‌های بالا را re-sync می‌کند (`syncClientZkUI`, `renderQueue`, `syncViewBtn`, `syncHashToggleBtn`, مودال‌های باز، …). باکس MTProto Auth به `data-i18n` مهاجرت داده شد؛ ۱۵ کلید جدید fa/en (تست parity `test_dashboard_i18n.py` پاس).

### UX-06 · شمارنده دانلود غیرواقعی — Severity: Data (بک‌اند)
- **باس:** `db.bump_downloads(obj_id)` بیرون از گارد `start is None` صدا می‌شد؛ هر درخواست Range (پریویو مدیا، `<video preload="metadata">`، probe مرورگر) هم +۱ می‌زد. فایل کاربر با ۰ دانلود واقعی «۲۷» نشان می‌داد.
- **فیکس (src/anbar/api/download.py):** bump فقط برای 200 کامل (بدون Range). درخواست‌های 206 و 304 شمرده نمی‌شوند. آمار per-link (v0.10.4) و cap لینک (v0.9.2) از قبل فقط full بودند — بدون تغییر.
- **تست:** `tests/test_download_counter.py` — ۳ تست: Range ×2 → counter=0؛ دو دانلود کامل → 2 سپس Range → همچنان 2؛ 304 با ETag → شمرده نمی‌شود.

### UX-07 · دکمه نمایش/پنهان API Hash — Severity: UI
- **باس:** فیلد همیشه خالی است (B-054: سرور hash خام را برنمی‌گرداند)؛ toggle نوع input روی فیلد خالی هیچ افکتی نداشت.
- **فیکس:** toggle حالا مقدار masked (مثل `abcd••••wxyz`) را در فیلد نشان می‌دهد و در حالت پنهان برمی‌گرداند به خالی. سرور از قبل مقدار حاوی `•` را در POST رد می‌کند، پس reveal هرگز نمی‌تواند hash ذخیره‌شده را بازنویسی کند. `_tgApiHashMasked` از `GET /admin/telegram-config` پر می‌شود.

### UX-08 (بونوس، حین E2E کشف شد) · ZIP استریم با MTProto کاملاً خراب بود — Severity: Critical (بک‌اند)
- **باس:** `zipper.stream_zip` کوروتین‌های `fetch_chunk` را روی یک event loop **جدید** در worker thread اجرا می‌کرد (`work_loop.run_until_complete`)؛ Telethon کلاینت MTProto به loop اصلی قفل است → `RuntimeError: The asyncio event loop must not change after connection` → هر ZIP واقعی وسط استریم ۵۰۰ می‌شد. تست‌ها fake backend دارند و این را هرگز نمی‌دیدند — در E2E واقعی روی loopback کشف شد.
- **فیکس (src/anbar/zipper.py):** `fetch_chunk` با `asyncio.run_coroutine_threadsafe(..., q_loop)` روی **loop اصلی** اجرا می‌شود؛ worker thread فقط zip را serialize می‌کند و روی future منتظر می‌ماند (timeout 600s). Consumer که `await q.get()` است همزمان loop را آزاد نگه می‌دارد — بدون deadlock.
- **تست واقعی:** فایل ۱۰۰KB آپلود و ZIP شد → `sha256` محتوای ZIP = sha فایل اصلی ✓.

- **تست:** کل suite **۳۵۱ سبز** (۳۴۸ قبلی + ۳ جدید) · ruff روی فایل‌های تغییر یافته تمیز.

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
