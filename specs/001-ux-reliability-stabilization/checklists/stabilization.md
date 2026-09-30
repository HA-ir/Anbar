# Implementation and Verification Checklist: Anbar Stabilization & UX Reliability

**Purpose**: Concrete, observable verification checklist for Anbar stabilization, covering functional, UX, reliability, performance, security, regression, deployment, and documentation requirements.  
**Created**: 2026-09-30  
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md) | [tasks.md](../tasks.md)

**Review Ownership**: Reviewer-owned verification and acceptance artifact. Mark an item `[x]` only when the specified observable evidence has been demonstrated and verified through automated tests or empirical inspection.

---

## 1. File Selection & Main-Thread Performance

- [ ] CHK001 **Single Selection**: Does clicking a file card or table row checkbox add its ID to `selSet` and apply `.selected` styling without triggering a layout recalculation or re-render of unrelated items? [Observable: `tr.classList.contains("selected") === true`, frame time < 16ms]
- [ ] CHK002 **Repeated Selection Toggling**: Does rapidly clicking the same item's checkbox 10 times alternate selection state deterministically without event listener accumulation or state de-synchronization? [Observable: `selSet.has(id)` strictly tracks final checkbox `.checked` state]
- [ ] CHK003 **Multi-Selection Range**: Does selecting multiple items consecutively update the selection action bar (`#selBar`) with the exact count of selected items? [Observable: `#selCnt.textContent` matches `selSet.size`]
- [ ] CHK004 **Large Selection Performance (500 Files)**: Does clicking "Select All" on a directory containing 500 files populate `selSet` and visually update all checkboxes in under 50ms without freezing the page? [Observable: Performance mark `duration < 50ms`, zero dropped frames]
- [ ] CHK005 **Select All Non-Destructive Invariant**: Does "Select All" update existing DOM nodes directly without calling `renderRows()`, `renderGallery()`, or re-instantiating `<video>`/`<img>` elements? [Observable: Existing DOM references in `#rows` or `.gallery` remain identical before and after select-all]
- [ ] CHK006 **Deselect All**: Does clicking "Deselect All" or exiting select mode clear `selSet`, remove `.selected` classes from all items, and hide `#selBar` immediately? [Observable: `selSet.size === 0`, `#selBar.style.display === "none"`]
- [ ] CHK007 **Selection While Search Is Active**: When a filter is applied in `#fSearch`, does "Select All" select only the currently visible filtered items rather than invisible un-filtered items? [Observable: `selSet.size === visibleFiles().length`]
- [ ] CHK008 **Selection During File Loading**: If files are actively being refreshed or loaded in the background, does user selection remain stable without being silently wiped by background responses? [Observable: `selSet` maintains user selections across background `refresh()` completions]
- [ ] CHK009 **Selection Cleanup on Move / Delete**: When selected items are successfully moved or deleted, are their IDs immediately removed from `selSet`? [Observable: No phantom IDs retained in `selSet` post-operation]
- [ ] CHK010 **Zero Runaway CPU / Event Storm**: Does holding a mouse down or dragging across checkboxes maintain CPU utilization under 15% without runaway event loops? [Observable: Profiler task duration < 16ms per event, zero recursive listener invocations]
- [ ] CHK011 **Memory Leak Absence**: Does repeatedly toggling "Select All" and "Deselect All" 50 times result in flat JS heap allocation without orphaned DOM nodes or unbound closures? [Observable: Heap snapshot shows detached DOM tree count remains 0]

---

## 2. File Move UX, Validation & Safety

- [ ] CHK012 **Single File Move Execution**: Can a single file be relocated to a target directory prefix and immediately appear in the destination folder? [Observable: Object row in SQLite reflects new `filename` prefix, response contains `{"moved": 1}`]
- [ ] CHK013 **Batch Move Execution**: Can multiple selected files (e.g. 10 files) be moved simultaneously to a target directory with complete atomic accounting? [Observable: `POST /api/v1/admin/objects/move` returns `moved: 10`, `skipped: []`]
- [ ] CHK014 **Destination Selection Interface**: Does `#moveModal` present clear interactive options to select Root (`/`), existing folder chips, or type a custom destination? [Observable: Root button sets `#moveDest.value = ""`, folder chips set corresponding paths]
- [ ] CHK015 **Same Destination Validation**: If the user selects the exact folder the items currently occupy, is the move blocked with an inline validation message? [Observable: Warning message displayed; `#moveOk` disabled; zero network API calls dispatched]
- [ ] CHK016 **Circular Folder Move Prevention**: If a user attempts to move a parent folder into its own subfolder (e.g. `docs/` into `docs/sub/`), is the move strictly blocked client-side? [Observable: Inline warning "Cannot move a folder into itself"; submission blocked]
- [ ] CHK017 **In-Flight Progress & Button Disabling**: While the move API call is pending, does `#moveModal` remain visible with an active loading spinner and disabled submit/cancel buttons? [Observable: `#moveOk.disabled === true`, `#moveCancel.disabled === true`, spinner visible]
- [ ] CHK018 **Granular Completion Feedback**: Upon move completion, does a toast notification display the exact count of moved items and any skipped items? [Observable: Toast text reads "X moved (Y skipped)"]
- [ ] CHK019 **Stale UI Cache Invalidation**: Following a move, is `folderViewCache` cleared and the current view refreshed automatically to reflect the updated hierarchy? [Observable: `folderViewCache.size === 0`, moved items disappear from source view without manual page reload]
- [ ] CHK020 **Move Modal Keyboard Usability**: Can `#moveModal` be closed with `Escape` (when not in-flight) and confirmed with `Enter` in the destination input, with focus trapped inside the modal? [Observable: Keyboard events trigger respective actions; `document.activeElement` stays within modal]

---

## 3. MKV & Media Playback Capability Detection

- [ ] CHK021 **Supported Container/Codec Native Playback**: In Chromium browsers supporting Matroska demuxing, does an MKV file containing H.264/AAC video play directly in the modal without showing an error banner? [Observable: `video.paused === false`, time advances, `.fm-fallback` is absent]
- [ ] CHK022 **Explicit Container Type Hints**: Does the `<video>` element include an explicit `<source>` element specifying `type="video/x-matroska"` or `type="video/webm"`? [Observable: DOM inspection shows `<source src="..." type="video/x-matroska">`]
- [ ] CHK023 **HTTP Range & 206 Partial Content Verification**: Does the server respond with `HTTP 206 Partial Content`, `Content-Range: bytes ...`, and `Accept-Ranges: bytes` when seeking video? [Observable: Network inspector confirms 206 status on byte-range requests]
- [ ] CHK024 **Granular Media Error Discrimination**: Does `video.onerror` inspect `video.error.code` to distinguish between genuine decode failures (`MEDIA_ERR_DECODE` / `MEDIA_ERR_SRC_NOT_SUPPORTED`) and network aborts (`MEDIA_ERR_NETWORK`)? [Observable: Network drop displays retry button; decode failure displays codec fallback notice]
- [ ] CHK025 **Informative Codec Fallback UI**: When a browser genuinely cannot decode an MKV's stream (e.g. unsupported DTS audio or missing codec), does the modal display an actionable message explaining codec incompatibility alongside a direct download button? [Observable: Download button triggers immediate download via `downloadFileWithZk(o)`]
- [ ] CHK026 **Corrupted/Invalid Media Handling**: If an MKV file has corrupted header bytes, does the player fail gracefully with a descriptive error rather than locking the UI or hanging the modal? [Observable: Modal remains responsive, close button works, error message is displayed]

---

## 4. Search Bar State Synchronization & Debounce Reliability

- [ ] CHK027 **Basic Query Filtering**: Does typing a string into `#fSearch` filter visible files and folders in real time after the 75ms debounce period? [Observable: Only items matching the query substring appear in `#rows` / `.gallery`]
- [ ] CHK028 **Synchronous Search Clear**: Does clicking `#fClear` ("×") immediately clear `#fSearch.value`, set `fQuery = ""`, hide the clear button, and restore full folder contents? [Observable: `#fSearch.value === ""`, `fQuery === ""`, full list rendered]
- [ ] CHK029 **Debounce Timer Cancellation on Clear**: When clearing the search bar within 75ms of typing, is `searchDebounceTimer` cancelled synchronously so that no pending callback fires with the stale query? [Observable: `clearTimeout(searchDebounceTimer)` executed; timer handle reset to `null`]
- [ ] CHK030 **Rapid Typing & Clearing Cycle**: Does rapidly typing "search", pressing clear, typing "new", and pressing clear leave the input empty without resurrecting "search"? [Observable: Input remains strictly empty after 1000ms delay; zero query resurrection]
- [ ] CHK031 **Cache Key Eviction on Clear**: Does clearing search invalidate search entries in `folderViewCache` so that stale cached DOM trees cannot be restored? [Observable: `folderViewCache` contains zero entries for the cleared query]
- [ ] CHK032 **History & Popstate Determinism**: When navigating between folders using browser back/forward buttons, does search state remain synchronized without injecting obsolete queries into the input? [Observable: Navigating to `#folder=...` does not re-populate `#fSearch` with previous queries]

---

## 5. Cold Startup & Deterministic Initialization

- [ ] CHK033 **Clean Cold-Start File Loading**: When the Anbar container/process is stopped and restarted, does navigating to `http://localhost:8567/` load all stored files immediately on first render without opening Settings? [Observable: `#rows tr` or `.gcell` elements populate within 1.5s of page load]
- [ ] CHK034 **Transparent 401 Re-Login and Retry**: When an admin session cookie is expired or uninitialized on page load, does `api()` obtain a fresh cookie via `/ui/login` and transparently retry the failed request once? [Observable: Request succeeds on retry; zero 401 errors surfaced to `refresh()`]
- [ ] CHK035 **Coalesced Re-Login Under Parallel Requests**: When `/api/v1/admin/status` and `/api/v1/admin/objects` fire concurrently on cold boot, does only ONE re-login request execute? [Observable: Network tab shows exactly one `POST /ui/login` call during bootstrap]
- [ ] CHK036 **SQLite Independence From Telegram Connection**: Does `GET /api/v1/admin/objects` return stored metadata from SQLite immediately even if the MTProto backend or Telegram connection is still in-flight or delayed? [Observable: Endpoint returns HTTP 200 within 50ms regardless of Telegram network state]
- [ ] CHK037 **Elimination of Settings Drawer Dependency**: Can an administrator restart the server 5 consecutive times and verify that files populate every time without ever clicking `#settingsBtn` or viewing Telegram Auth? [Observable: 5/5 cold restart cycles render files automatically]
- [ ] CHK038 **Graceful Error Banner on True Outage**: If the database is genuinely unreachable, does `#netBanner` display a sticky retry banner rather than permanently breaking the UI layout? [Observable: `#netBanner` displays with "Retry" action]

---

## 6. Falkenstein Production Deployment & Health Checks

- [ ] CHK039 **Absolute Volume Path Enforcement**: On Falkenstein, does the production container `anbar-anbar-1` mount `/opt/anbar/data`, `/opt/anbar/secrets`, and `/opt/anbar/.env`? [Observable: `docker inspect anbar-anbar-1` confirms Source paths are `/opt/anbar/*`]
- [ ] CHK040 **Zero Local Deployment Credentials Committed**: Are all deployment helpers, SSH scripts, tokens, and remote IP configs located outside the Git working tree? [Observable: `git status` shows zero tracked or staged deployment helper files]
- [ ] CHK041 **Remote Container Health Status**: Following deployment on Falkenstein, does Docker report the container as healthy? [Observable: `docker ps` outputs `Up (healthy)` for `anbar-anbar-1`]
- [ ] CHK042 **Healthcheck Endpoint Validation**: Does `curl -s http://127.0.0.1:8318/healthz` on the remote host return HTTP 200 with service status "ok"? [Observable: JSON response `{"status":"ok","service":"anbar","version":"..."}`]
- [ ] CHK043 **Public TLS Proxy Verification**: Does `curl -s https://dl.amiri-dev.ir/healthz` return HTTP 200 over TLS through Nginx? [Observable: HTTP 200 response with valid SSL certificate]
- [ ] CHK044 **Production Data Integrity Verification**: Does the production SQLite database at `/opt/anbar/data/anbar.db` remain intact with all existing object records, manifests, and audit logs preserved? [Observable: Object count matches pre-deployment count; zero missing files]

---

## 7. Documentation & Working Record Compliance

- [ ] CHK045 **Working Record Up-to-Date**: Is `docs/WORKING_RECORD.md` updated at the end of the session with objectives, changes, test counts, git commit, and next steps? [Observable: Entry for Session 6 present and synchronized with current commit]
- [ ] CHK046 **Changelog Updated**: Does `CHANGELOG.md` document all stabilization fixes under the active version using Keep a Changelog formatting? [Observable: Entries under `[0.15.57]` or active section]
- [ ] CHK047 **Bug Tracker Synchronized**: Does `BUGS_AND_FIXES.md` document the root causes, fixes, and prevention guidance for the resolved defects? [Observable: Bug entries logged with technical details]
- [ ] CHK048 **Audit Coverage Matrix Updated**: Is `AUDIT_COVERAGE.md` updated with `[x]` flags for audited and fixed modules? [Observable: `src/anbar/ui/index.html` selection, move, search, and startup sections marked audited]
- [ ] CHK049 **Zero Unresolved Ambiguities or Risks**: Are all known edge cases, limitations, and operational boundaries recorded in documentation before declaring completion? [Observable: No lingering TODOs in specification or active documentation]
