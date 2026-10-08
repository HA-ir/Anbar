# Settings UI/UX Comprehensive Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform Anbar's Settings Drawer from a monolithic, unorganized form into a modern, card-based, responsive management center with clean tab navigation, intuitive Telegram configuration groupings, polished RTL/LTR ergonomics, and responsive save/restart feedback.

**Architecture:** Refactor the settings drawer structure in `src/anbar/ui/index.html` into 6 streamlined functional tabs with card containers. Retain 100% of existing API bindings (`/api/v1/admin/settings`, `/api/v1/admin/telegram-config`, `/api/v1/admin/system-stats`, `/api/v1/admin/api-keys`, etc.) while eliminating obsolete inline styles, repairing broken tab scrolling, and improving visual hierarchy using Anbar's design tokens.

**Tech Stack:** Vanilla JavaScript (ES6+), HTML5, CSS3 Custom Properties (Design Tokens), Playwright (Python E2E testing).

**Spec:** Section 5 & UX-01/UX-03 in `IMPROVEMENT_PLAN.md`, plus user requirements for Telegram settings organization, owner authorization, and directory management.

---

## Global Constraints

- Preserve all existing input IDs (`#s_tg_backend`, `#s_tg_ingest_strategy`, `#s_tg_ingest_concurrency`, `#s_tg_owner_ids`, `#s_tg_webhook_secret`, `#s_tg_bot_tokens`, `#s_rate_download`, etc.) so that all automated tests and backend update handlers continue functioning without regression.
- Maintain full bilingual support (`I18N.fa` and `I18N.en`).
- Preserve keyboard shortcuts (Esc to close, Enter to submit where applicable).
- Support responsive viewport breakpoints (<768px slide-in drawer, >=768px two-column desktop modal).
- Enforce strict RTL/LTR styling: English technical inputs (tokens, IDs, hashes, phone numbers) must remain strictly LTR with monospaced typography, while labels and descriptions align naturally in Persian RTL.

## Review Focus

1. **Tab Navigation Sync:** Every setting section must belong to a visible tab; clicking any tab must smoothly scroll to its container, and scrolling through sections must highlight the matching tab in real time.
2. **Form Persistence Integrity:** Editing any combination of settings across multiple tabs must be saved cleanly upon clicking `#saveBtn` without dropping unedited fields or wiping masked credentials.
3. **Telegram Login Lifecycle:** The interactive MTProto authentication box (phone -> code -> 2FA) must render seamlessly within the new Telegram card structure.
4. **Mobile Usability (<768px):** No horizontal page overflow, touch-friendly tab pills with minimum 44px tap targets, and sticky header/footer navigation.
5. **Zero Test Regressions:** All 525+ automated tests and existing Playwright E2E tests must pass green.

---

### Task 1: Navigation Architecture & Section Restructuring

**Files:**
- Modify: `src/anbar/ui/index.html:931-1305` (drawer markup & navigation structure)
- Modify: `src/anbar/ui/index.html:5195-5250` (tab selection & scroll spy logic)
- Test: `tests/test_e2e_playwright.py`

**Interfaces:**
- Consumes: `#drawer`, `.drawer-nav`, `.dtab`, `.drawer-body`, `setActiveTab()`.
- Produces: 6 consolidated sections (`#secUI`, `#secTelegram`, `#secSecurity`, `#secPerformance`, `#secSystem`), with consistent ID anchoring and active scroll observation.

- [ ] **Step 1: Write failing Playwright test for settings tab navigation and section anchoring**

```python
def test_settings_tab_navigation_and_section_sync(authed_page: Page):
    """Verify that all 6 settings tabs exist, click smoothly, and anchor to matching sections."""
    page = authed_page
    page.click("#setBtn")
    page.wait_for_selector("#drawer.on", timeout=6000)

    expected_tabs = ["all", "secUI", "secTelegram", "secSecurity", "secPerformance", "secSystem"]
    for tab_key in expected_tabs:
        loc = page.locator(f'.dtab[data-sec="{tab_key}"]')
        assert loc.is_visible(), f"Tab {tab_key} must be visible"

    # Click Telegram tab
    page.click('.dtab[data-sec="secTelegram"]')
    page.wait_for_function("() => document.querySelector('.dtab[data-sec=\"secTelegram\"]').classList.contains('active')", timeout=3000)
    assert page.locator("#secTelegram").is_visible()

    # Click Performance tab
    page.click('.dtab[data-sec="secPerformance"]')
    page.wait_for_function("() => document.querySelector('.dtab[data-sec=\"secPerformance\"]').classList.contains('active')", timeout=3000)
    assert page.locator("#secPerformance").is_visible()

    page.click("#setClose")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_e2e_playwright.py -k test_settings_tab_navigation_and_section_sync`
Expected: FAIL (tab keys like `secTelegram` and `secPerformance` do not yet exist).

- [ ] **Step 3: Restructure drawer navigation and sections in `src/anbar/ui/index.html`**

Update `.drawer-nav` tabs and wrap all drawer content into the 5 primary category sections + `all`:
1. `tabAll` (`data-sec="all"`): Show all sections
2. `tabUI` (`data-sec="secUI"`): Appearance & Preferences
3. `tabTg` (`data-sec="secTelegram"`): Telegram Storage & Ingest Engine
4. `tabSecurity` (`data-sec="secSecurity"`): Access Control, Owner IDs, Keys & ZK
5. `tabPerformance` (`data-sec="secPerformance"`): Limits, Rates & Cache
6. `tabSystem` (`data-sec="secSystem"`): System Telemetry, Backup & Audit Logs

Update `_secKeys` in JS:
```javascript
const _secKeys = ["secUI", "secTelegram", "secSecurity", "secPerformance", "secSystem"];
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_e2e_playwright.py -k test_settings_tab_navigation_and_section_sync`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/anbar/ui/index.html tests/test_e2e_playwright.py
git commit -m "feat(ui): consolidate settings drawer tabs and repair scroll spy navigation"
```

---

### Task 2: Telegram Settings Card-Based Modular Redesign

**Files:**
- Modify: `src/anbar/ui/index.html:1090-1230` (HTML markup for `#secTelegram`)
- Modify: `src/anbar/ui/index.html:445-515` (CSS styling for settings cards)
- Test: `tests/test_e2e_playwright.py`

**Interfaces:**
- Consumes: `#secTelegram`, all existing input IDs (`#s_tg_backend`, `#s_tg_ingest_strategy`, `#s_tg_ingest_concurrency`, `#s_tg_owner_ids`, `#s_tg_webhook_secret`, `#s_tg_channel_id`, `#s_tg_api_id`, `#s_tg_api_hash`, `#s_tg_peer`, `#s_tg_chunk_size`, etc.).
- Produces: 4 visual cards with clear headings, badges, and grouped controls:
  - Card 1: `tgCardAuth` (MTProto Session & Test Connection)
  - Card 2: `tgCardStrategy` (Ingest Speed Mode, Concurrency & Storage Backend)
  - Card 3: `tgCardStorage` (Bot Tokens Pool & Storage Channel)
  - Card 4: `tgCardAccess` (Owner IDs & Webhook Management)
  - Card 5: `tgCardDev` (Developer Credentials: API ID & Hash)

- [ ] **Step 1: Write failing Playwright test for Telegram cards layout and input visibility**

```python
def test_telegram_settings_cards_rendered(authed_page: Page):
    """Verify that Telegram settings are organized into designated cards and all inputs retain IDs."""
    page = authed_page
    page.click("#setBtn")
    page.wait_for_selector("#drawer.on", timeout=6000)

    # All required inputs must be accessible and inside cards
    required_ids = [
        "#s_tg_backend",
        "#s_tg_ingest_strategy",
        "#s_tg_ingest_concurrency",
        "#s_tg_channel_id",
        "#s_tg_owner_ids",
        "#s_tg_webhook_secret",
        "#btnTgTestConn",
        "#btnTgSetWebhook",
    ]
    for sel in required_ids:
        assert page.locator(sel).is_visible(), f"{sel} must be visible in Telegram settings"

    # Card containers exist
    assert page.locator(".set-card").count() >= 4

    page.click("#setClose")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_e2e_playwright.py -k test_telegram_settings_cards_rendered`
Expected: FAIL (`.set-card` elements not found).

- [ ] **Step 3: Implement `.set-card` CSS styles and modularize `#secTelegram` HTML**

In CSS:
```css
.set-card {
  background: var(--bg2);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 16px;
  box-shadow: 0 1px 3px rgba(0,0,0,.04);
}
.set-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--line);
}
.set-card-title {
  font-size: 13.5px;
  font-weight: 700;
  color: var(--tx);
  display: flex;
  align-items: center;
  gap: 8px;
}
```

Reorganize `#secTelegram` into the 4 structured `.set-card` containers, eliminating unformatted inline styles.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_e2e_playwright.py -k test_telegram_settings_cards_rendered`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/anbar/ui/index.html tests/test_e2e_playwright.py
git commit -m "feat(ui): redesign telegram settings into structured visual cards"
```

---

### Task 3: Security, Limits & Cache Modernization

**Files:**
- Modify: `src/anbar/ui/index.html:1010-1090` (HTML markup for `#secSecurity` and `#secPerformance`)
- Test: `tests/test_e2e_playwright.py`

- [ ] **Step 1: Write failing Playwright test for Security and Performance card layouts**

```python
def test_security_and_performance_cards_rendered(authed_page: Page):
    """Verify security keys, ZK controls, rate limits, and cache controls inside styled cards."""
    page = authed_page
    page.click("#setBtn")
    page.wait_for_selector("#drawer.on", timeout=6000)

    # Click Security tab
    page.click('.dtab[data-sec="secSecurity"]')
    assert page.locator("#swAuth").is_visible()
    assert page.locator("#swEnc").is_visible()
    assert page.locator("#swClientZk").is_visible()
    assert page.locator("#mkKeyBtn").is_visible()

    # Click Performance tab
    page.click('.dtab[data-sec="secPerformance"]')
    assert page.locator("#s_rate_download").is_visible()
    assert page.locator("#s_max_upload_mb").is_visible()
    assert page.locator("#swCache").is_visible()
    assert page.locator("#purgeBtn").is_visible()

    page.click("#setClose")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_e2e_playwright.py -k test_security_and_performance_cards_rendered`
Expected: FAIL.

- [ ] **Step 3: Implement modular cards for `#secSecurity` and `#secPerformance`**

1. In `#secSecurity`:
   - *Card: Access & Authentication* (`#swAuth`, API Key creation `#mkKeyBtn` + `#keyList`)
   - *Card: Data Encryption & Master Secret* (`#swEnc`, `#s_enc_secret`, visibility toggle, rotate button)
   - *Card: Client-Side True ZK* (`#swClientZk`, `#s_client_zk_pass`, visibility toggle)
2. In `#secPerformance`:
   - *Card: Rate Limits & Bandwidth* (`#s_rate_download`, `#s_rate_upload`, `#s_rate_login`)
   - *Card: Upload Quotas & Sessions* (`#s_max_upload_mb`, `#s_session_ttl_h`)
   - *Card: Download Cache* (`#swCache`, `#s_cache_mb`, `#cacheNow`, `#purgeBtn`)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_e2e_playwright.py -k test_security_and_performance_cards_rendered`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/anbar/ui/index.html tests/test_e2e_playwright.py
git commit -m "feat(ui): organize security, rate limits, and cache controls into modular cards"
```

---

### Task 4: System Health, Backup & Audit Logs Visual Polish

**Files:**
- Modify: `src/anbar/ui/index.html:1230-1300` (HTML markup for `#secSystem`)
- Test: `tests/test_e2e_playwright.py`

- [ ] **Step 1: Write Playwright test asserting system health stats and backup controls**

```python
def test_system_health_and_backup_controls(authed_page: Page):
    """Verify system telemetry stat grid, storage distribution bar, and backup action buttons."""
    page = authed_page
    page.click("#setBtn")
    page.wait_for_selector("#drawer.on", timeout=6000)

    page.click('.dtab[data-sec="secSystem"]')
    assert page.locator(".stat-grid").is_visible()
    assert page.locator("#storageDistBar").is_visible()
    assert page.locator("#btnDownloadBackup").is_visible()
    assert page.locator("#btnPushTgBackup").is_visible()
    assert page.locator("#btnChannelRebuild").is_visible()
    assert page.locator("#auditLogList").is_visible()

    page.click("#setClose")
```

- [ ] **Step 2: Run test to verify behavior**

Run: `uv run pytest tests/test_e2e_playwright.py -k test_system_health_and_backup_controls`

- [ ] **Step 3: Enhance `#secSystem` cards layout**

1. *Card: System Metrics & Health* (Stat grid with subtle border styling, storage percentage indicator, color-coded storage breakdown bar with interactive tooltips).
2. *Card: Automated Maintenance* (Daily Telegram backup switch, ffmpeg subtitle extraction switch with clean badge).
3. *Card: Database & Disaster Recovery* (Download, import, Telegram push, and channel rebuild buttons with consistent sizing).
4. *Card: Security Audit Logs* (Log container with refresh button and readable timestamp rows).

- [ ] **Step 4: Run test and verify pass**

Run: `uv run pytest tests/test_e2e_playwright.py -k test_system_health_and_backup_controls`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/anbar/ui/index.html tests/test_e2e_playwright.py
git commit -m "feat(ui): polish system telemetry, disaster recovery, and audit log cards"
```

---

### Task 5: Interactive Dirty State Tracking & Restart UX

**Files:**
- Modify: `src/anbar/ui/index.html:5335-5350, 6000-6050` (dirty state logic & restart banner)
- Test: `tests/test_e2e_playwright.py`

- [ ] **Step 1: Write failing Playwright test for dirty state notification and restart feedback**

```python
def test_settings_dirty_state_and_restart_banner(authed_page: Page):
    """Verify modifying a .env setting displays a clear restart notice and save state."""
    page = authed_page
    page.click("#setBtn")
    page.wait_for_selector("#drawer.on", timeout=6000)

    # Change channel ID
    page.fill("#s_tg_channel_id", "-100999888777")
    page.locator("#s_tg_channel_id").dispatch_event("input")

    # Restart banner should become visible
    banner = page.locator("#restartNoticeBanner")
    assert banner.is_visible()

    page.click("#setClose")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_e2e_playwright.py -k test_settings_dirty_state_and_restart_banner`
Expected: FAIL (`#restartNoticeBanner` not found).

- [ ] **Step 3: Implement `#restartNoticeBanner` and real-time dirty tracking in `index.html`**

Add an unobtrusive, stylish restart notification banner above the footer:
```html
<div id="restartNoticeBanner" style="display:none;background:var(--warn-soft);border:1px solid var(--warn);border-radius:10px;padding:10px 14px;margin-bottom:12px;font-size:12.5px;color:var(--tx);align-items:center;justify-content:space-between;gap:10px">
  <div style="display:flex;align-items:center;gap:8px">
    <span>⚠️</span>
    <span data-i18n="restartNeededNotice">تغییرات اعمال‌شده پس از ری‌استارت سرویس فعال خواهند شد.</span>
  </div>
  <button type="button" class="btn btn-warn" id="btnBannerRestart" style="padding:4px 10px;font-size:11.5px" data-i18n="restartNow">ری‌استارت</button>
</div>
```

Bind `input` and `change` events on all inputs with `data-dirty-key` to reveal the banner if any key in `RESTART_KEYS` is modified.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_e2e_playwright.py -k test_settings_dirty_state_and_restart_banner`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/anbar/ui/index.html tests/test_e2e_playwright.py
git commit -m "feat(ui): add real-time dirty state tracking and contextual restart banner"
```

---

### Task 6: Design Tokens, Typography & Full Bilingual RTL/LTR Polish

**Files:**
- Modify: `src/anbar/ui/index.html:1560-1850` (I18N strings)
- Modify: `src/anbar/ui/index.html:445-520` (CSS tokens & typography rules)
- Test: Full test suite (`pytest tests/`)

- [ ] **Step 1: Check for any missing i18n keys or broken translations**
  Ensure all newly structured cards, subtitles, and buttons have complete Persian (`I18N.fa`) and English (`I18N.en`) entries.

- [ ] **Step 2: Enforce strict LTR alignment on all credential fields**
  Ensure `#s_tg_api_id`, `#s_tg_api_hash`, `#s_tg_owner_ids`, `#s_tg_webhook_secret`, `#s_tg_channel_id`, `#s_enc_secret`, and `#s_client_zk_pass` have `direction: ltr !important; text-align: left` to prevent cursor jumping in Persian mode.

- [ ] **Step 3: Run full automated test suite to ensure 100% compliance**

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/anbar
uv run pytest
```

- [ ] **Step 4: Commit changes**

```bash
git add src/anbar/ui/index.html tests/
git commit -m "style(ui): polish typography, design tokens, and RTL/LTR bidirectionality"
```

---

### Task 7: Falkenstein Production Deployment & Smoke Verification

**Files:**
- Modify: `docs/WORKING_RECORD.md`

- [ ] **Step 1: Commit and push clean working tree to `origin/main`**
- [ ] **Step 2: Deploy to Falkenstein via `/home/hossein/anbar_deploy_falkenstein.sh`**
- [ ] **Step 3: Verify public health check `https://dl.amiri-dev.ir/healthz`**
- [ ] **Step 4: Perform interactive browser verification on `https://dl.amiri-dev.ir/`**
- [ ] **Step 5: Record deployment evidence in `docs/WORKING_RECORD.md`**

---
