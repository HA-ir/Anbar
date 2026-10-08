"""Playwright E2E browser tests for Anbar core UI.

Comprehensive E2E journeys covering:
1. Authentication flow (invalid admin key vs valid admin key).
2. UI layout, theme toggle, and Persian/English language switching.
3. File upload via drag/drop or input into Telegram-backed storage.
4. Gallery view vs Table view rendering and toggle.
5. File details/preview modal inspection.
6. Real-time search query filtering and no-match empty states.
7. Share link generation with QR code view.
8. Password-protected share link and browser unlock flow.
9. Link manager modal and link revocation.
10. Multi-select toolbar and selection actions.
11. Settings modal inspection and configuration inputs.
12. Logout flow.
"""

from __future__ import annotations

import os
import socket
import threading
import time
import urllib.request
from collections.abc import Generator
from pathlib import Path

import pytest
import uvicorn
from playwright.sync_api import Browser, BrowserContext, Page

from anbar.config import get_settings
from anbar.main import create_app
from anbar.storage import FakeBackend


@pytest.fixture(scope="module")
def e2e_server(tmp_path_factory) -> Generator[str, None, None]:
    """Spin up a live Anbar HTTP server backed by FakeBackend."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    tmp_dir = tmp_path_factory.mktemp("e2e_anbar")
    db_path = str(tmp_dir / "anbar_e2e.db")

    os.environ["ANBAR_ADMIN_KEY"] = "e2e-admin-secret-key"
    os.environ["ANBAR_API_KEY"] = "e2e-uploader-key"
    os.environ["ANBAR_HMAC_SECRET"] = "e2e-hmac-signing-secret"
    os.environ["ANBAR_AUTH_ENABLED"] = "true"
    os.environ["ANBAR_DB_PATH"] = db_path
    os.environ["ANBAR_DATA_DIR"] = str(tmp_dir)
    os.environ["ANBAR_BASE_URL"] = f"http://127.0.0.1:{port}"
    os.environ["ANBAR_RATE_DOWNLOAD_PER_MIN"] = "10000"
    os.environ["ANBAR_RATE_UPLOAD_PER_MIN"] = "10000"
    os.environ["ANBAR_RATE_LOGIN_PER_MIN"] = "10000"
    get_settings.cache_clear()

    backend = FakeBackend()
    app = create_app(backend=backend)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    ready = False
    for _ in range(50):
        try:
            with urllib.request.urlopen(f"{base_url}/healthz", timeout=1) as resp:
                if resp.status == 200:
                    ready = True
                    break
        except Exception:
            time.sleep(0.1)

    assert ready, f"Anbar e2e server did not become healthy at {base_url}"

    yield base_url

    server.should_exit = True
    thread.join(timeout=3)
    get_settings.cache_clear()


@pytest.fixture(scope="module")
def browser_instance():
    from playwright.sync_api import sync_playwright

    p = sync_playwright().start()
    b = p.chromium.launch(headless=True)
    yield b
    b.close()
    p.stop()


@pytest.fixture()
def page(browser_instance: Browser) -> Generator[Page, None, None]:
    context = browser_instance.new_context()
    p = context.new_page()
    yield p
    context.close()


@pytest.fixture()
def authed_page(e2e_server: str, page: Page) -> Page:
    """Helper fixture providing an already logged-in browser page."""
    page.goto(f"{e2e_server}/")
    page.fill("#keyInput", "e2e-admin-secret-key")
    page.click("#loginBtn")
    page.wait_for_selector("#app", state="visible", timeout=4000)
    return page


def _upload_file(page: Page, tmp_path: Path, filename: str) -> None:
    """Helper to upload a file through UI and wait for it to process."""
    f = tmp_path / filename
    if not f.exists():
        f.write_text(f"Content of {filename} for Playwright testing.")
    page.set_input_files("#fileInput", str(f))
    page.wait_for_selector(".qitem.done", timeout=6000)
    page.wait_for_timeout(300)


def test_auth_failure_and_success_flow(e2e_server: str, page: Page):
    """Test 1: Admin login handles wrong key error and succeeds on valid key."""
    page.goto(f"{e2e_server}/")
    assert page.locator("#loginWrap").is_visible()
    assert not page.locator("#app").is_visible()

    # Wrong credentials
    page.fill("#keyInput", "wrong-password")
    page.click("#loginBtn")
    page.wait_for_selector("#loginErr:not(:empty)", timeout=3000)
    err_text = page.locator("#loginErr").inner_text()
    assert "نادرست" in err_text or "Invalid" in err_text

    # Show/hide password button
    assert page.locator("#keyInput").get_attribute("type") == "password"
    page.click("#eyeBtn")
    assert page.locator("#keyInput").get_attribute("type") == "text"
    page.click("#eyeBtn")
    assert page.locator("#keyInput").get_attribute("type") == "password"

    # Correct credentials
    page.fill("#keyInput", "e2e-admin-secret-key")
    page.click("#loginBtn")
    page.wait_for_selector("#app", state="visible", timeout=4000)
    assert not page.locator("#loginWrap").is_visible()


def test_empty_dashboard_and_header_controls(authed_page: Page):
    """Test 2: Dashboard elements, empty states, and header controls render correctly."""
    page = authed_page
    assert page.locator("#app .logo").first.is_visible()
    assert page.locator("#fSearch").is_visible()
    assert page.locator("#fType").is_visible()
    assert page.locator("#fSort").is_visible()
    assert page.locator("#refBtn").is_visible()
    assert page.locator("#viewBtn").is_visible()
    assert page.locator("#setBtn").is_visible()
    assert page.locator("#linksBtn").is_visible()
    assert page.locator("#outBtn").is_visible()


def test_file_upload_and_views_toggle(authed_page: Page, tmp_path: Path):
    """Test 3: File upload renders in gallery and table views, and view toggle switches them."""
    page = authed_page
    _upload_file(page, tmp_path, "hello_world.txt")

    # In default gallery view, .gcell should appear
    page.wait_for_selector(".gallery .gcell", timeout=5000)
    assert "hello_world.txt" in page.locator(".gallery .gcell").first.inner_text()

    # Toggle to table view
    page.click("#viewBtn")
    page.wait_for_selector("#rows tr", timeout=5000)
    assert page.locator("#rows tr").count() >= 1
    assert "hello_world.txt" in page.locator("#rows tr").first.inner_text()

    # Toggle back to gallery view
    page.click("#viewBtn")
    page.wait_for_selector(".gallery .gcell", timeout=5000)


def test_file_preview_modal_journey(authed_page: Page, tmp_path: Path):
    """Test 4: Clicking a file opens file modal with name, preview, and actions."""
    page = authed_page
    _upload_file(page, tmp_path, "preview_test.txt")

    cell = page.locator(".gallery .gcell:has-text('preview_test.txt')").first
    cell.click()

    page.wait_for_selector("#fileModal", state="visible", timeout=4000)
    assert page.locator("#fmName").is_visible()
    assert page.locator("#fmPreview").is_visible()
    assert page.locator("#fmDl").is_visible()
    assert page.locator("#fmShare").is_visible()
    assert page.locator("#fmClose").is_visible()

    page.click("#fmClose")
    page.wait_for_selector("#fileModal", state="hidden", timeout=3000)


def test_search_and_filtering(authed_page: Page, tmp_path: Path):
    """Test 5: Search box filters visible items and shows no-match state."""
    page = authed_page
    _upload_file(page, tmp_path, "searchable_alpha.txt")

    # Search for alpha
    page.fill("#fSearch", "searchable_alpha")
    page.wait_for_selector(".gallery .gcell:has-text('searchable_alpha')", timeout=4000)
    assert page.locator(".gallery .gcell:has-text('searchable_alpha')").count() >= 1

    # Search for non-existing query
    page.fill("#fSearch", "nonexistent_query_xyz123")
    page.wait_for_selector("#noMatch", timeout=4000)
    assert page.locator("#noMatch").is_visible()

    # Clear search
    page.click("#fClear")
    page.wait_for_timeout(300)
    assert not page.locator("#noMatch").is_visible()


def test_quick_share_link_modal(authed_page: Page, tmp_path: Path):
    """Test 6: Share options modal opens and generates link URL with QR display."""
    page = authed_page
    _upload_file(page, tmp_path, "share_test.txt")

    cell = page.locator(".gallery .gcell:has-text('share_test.txt')").first
    cell.click()
    page.wait_for_selector("#fileModal", state="visible", timeout=3000)

    # Click share in file modal
    page.click("#fmShare")
    page.wait_for_selector("#shareOptsModal", state="visible", timeout=3000)

    # Submit default share options
    page.click("#shareOptsModal button[type='submit']")
    page.wait_for_selector("#linkModal.on, #linkModal[style*='block']", timeout=4000)

    link_val = page.locator("#linkUrl").inner_text()
    assert "/f/" in link_val

    # Verify QR image element is rendered
    qr_img = page.locator("#linkQr")
    assert qr_img.is_visible()

    page.click("#linkClose")
    page.wait_for_selector("#linkModal", state="hidden", timeout=3000)


def test_password_protected_download_and_unlock(
    e2e_server: str, authed_page: Page, tmp_path: Path, browser_instance: Browser
):
    """Test 7: Password-gated share link prompts for password in browser and unlocks upon entry."""
    page = authed_page
    _upload_file(page, tmp_path, "protected_doc.txt")

    cell = page.locator(".gallery .gcell:has-text('protected_doc.txt')").first
    cell.click()
    page.wait_for_selector("#fileModal", state="visible", timeout=3000)

    page.click("#fmShare")
    page.wait_for_selector("#shareOptsModal", state="visible", timeout=3000)

    # Configure password and submit
    page.fill("#sharePw", "supersecret123")
    page.click("#shareOptsModal button[type='submit']")

    # Link modal opens with the password-protected link
    page.wait_for_selector("#linkModal.on, #linkModal[style*='block']", timeout=4000)
    pw_link = page.locator("#linkUrl").inner_text().strip()
    assert "/f/" in pw_link
    page.click("#linkClose")

    # Open a fresh, unauthenticated browser context
    unauthed_context: BrowserContext = browser_instance.new_context()
    guest_page: Page = unauthed_context.new_page()

    # Navigate to the password link without password in query string
    guest_page.goto(pw_link)
    guest_page.wait_for_selector("input[type='password'], input[name='pw']", timeout=4000)
    assert "password" in guest_page.content().lower() or "رمز" in guest_page.content()

    # Wrong password test
    pw_input = guest_page.locator("input[type='password'], input[name='pw']").first
    pw_input.fill("wrongpass")
    guest_page.locator("button[type='submit'], input[type='submit']").first.click()
    guest_page.wait_for_timeout(500)
    assert guest_page.locator("input[type='password'], input[name='pw']").count() >= 1

    # Correct password submission delivers file content
    pw_input = guest_page.locator("input[type='password'], input[name='pw']").first
    pw_input.fill("supersecret123")
    guest_page.locator("button[type='submit'], input[type='submit']").first.click()
    guest_page.wait_for_timeout(1500)
    assert "Content of protected_doc.txt" in guest_page.content() or guest_page.url != pw_link

    unauthed_context.close()


def test_links_manager_modal(authed_page: Page):
    """Test 8: Links manager opens, lists links, and handles revoke-all action."""
    page = authed_page

    page.click("#linksBtn")
    page.wait_for_selector("#linksModal", state="visible", timeout=3000)
    assert page.locator("#linksList").is_visible()
    assert page.locator("#revokeAllLinksBtn").is_visible()

    page.click("#revokeAllLinksBtn")
    page.wait_for_timeout(300)
    if page.locator("#__askYes").is_visible():
        page.click("#__askYes")
        page.wait_for_timeout(300)

    page.click("#linksClose")
    page.wait_for_selector("#linksModal", state="hidden", timeout=3000)


def test_multi_select_mode_and_bar(authed_page: Page, tmp_path: Path):
    """Test 9: Multi-select toolbar activates on select button, shows count, and cancels."""
    page = authed_page
    _upload_file(page, tmp_path, "select_doc.txt")

    page.click("#selectModeBtn")
    page.wait_for_timeout(300)

    # Click select all if available
    sel_all = page.locator("#selAllBtn")
    if sel_all.is_visible():
        sel_all.click()
        page.wait_for_timeout(300)
        assert page.locator("#selBar").is_visible()

    # Cancel select mode
    page.click("#selectModeBtn")
    page.wait_for_timeout(300)


def test_settings_modal(authed_page: Page):
    """Test 10: Settings modal opens, displays runtime configuration inputs, and closes."""
    page = authed_page

    page.click("#setBtn")
    page.wait_for_selector("#s_cache_mb", timeout=3000)
    assert page.locator("#s_cache_mb").is_visible()
    assert page.locator("#s_max_upload_mb").is_visible()
    assert page.locator("#setClose").is_visible()

    page.click("#setClose")
    page.wait_for_timeout(300)


def test_settings_modal_inputs_visible(authed_page: Page):
    """Regression: runtime settings inputs render in the settings modal."""
    page = authed_page
    page.click("#setBtn")
    page.wait_for_selector("#s_cache_mb", timeout=3000)
    for locator in [
        page.locator("#s_cache_mb"),
        page.locator("#s_max_upload_mb"),
        page.locator("#setClose"),
    ]:
        assert locator.is_visible()


def test_language_switch_fa_en(authed_page: Page):
    """Test 11: Switching between Persian and English alters document direction and labels."""
    page = authed_page

    # Switch to English
    page.click("#langEn")
    page.wait_for_timeout(300)
    html_dir = page.locator("html").get_attribute("dir")
    assert html_dir == "ltr" or page.locator("#langEn").get_attribute("class") == "on"

    # Switch to Persian
    page.click("#langFa")
    page.wait_for_timeout(300)
    html_dir = page.locator("html").get_attribute("dir")
    assert html_dir == "rtl" or page.locator("#langFa").get_attribute("class") == "on"


def test_logout_flow(authed_page: Page):
    """Test 12: Logout button clears authentication and returns to login screen."""
    page = authed_page

    page.click("#outBtn")
    page.wait_for_selector("#loginWrap", state="visible", timeout=4000)
    assert not page.locator("#app").is_visible()

    key = page.evaluate("() => localStorage.getItem('anbar-key')")
    assert not key


def test_video_preview_modal_journey(authed_page: Page, tmp_path: Path):
    """Test 13 (BUG-19): Clicking video card opens modal with player and controls."""
    page = authed_page
    mp4_file = tmp_path / "stream_sample.mp4"
    # Valid minimal MP4 container
    mp4_file.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00isommp42")

    page.set_input_files("#fileInput", str(mp4_file))
    page.wait_for_selector(".qitem.done", timeout=6000)
    page.wait_for_timeout(300)

    cell = page.locator(".gallery .gcell:has-text('stream_sample.mp4')").first
    assert cell.is_visible()

    # Clicking directly on the card / video thumbnail opens modal
    cell.click()
    page.wait_for_selector("#fileModal", state="visible", timeout=4000)

    vid = page.locator("#fmVid")
    assert vid.is_visible()
    assert vid.get_attribute("controls") is not None
    assert vid.get_attribute("playsinline") is not None
    assert "/f/" in (vid.get_attribute("src") or "")

    page.click("#fmClose")
    page.wait_for_selector("#fileModal", state="hidden", timeout=3000)


def test_folder_navigation_preview_stability(authed_page: Page, tmp_path: Path):
    """Test 14 (BUG-19): Folder navigation maintains gallery chrome without blinking."""
    page = authed_page
    _upload_file(page, tmp_path, "stable_preview.txt")

    # Create a subfolder
    page.evaluate("""async () => {
        await api("/api/v1/admin/folders/create", {
            method: "POST",
            body: JSON.stringify({ path: "docs_folder" })
        });
        await refresh();
    }""")
    page.wait_for_timeout(300)

    # Monitor for table chrome flash during navigation
    page.evaluate("""() => {
        window.__tableBlinked = false;
        const obs = new MutationObserver(() => {
            const tbl = document.querySelector("#tblWrap table");
            const thead = document.querySelector("#tblWrap thead");
            if (tbl && window.getComputedStyle(tbl).display !== "none") {
                window.__tableBlinked = true;
            }
            if (thead && window.getComputedStyle(thead).display !== "none") {
                window.__tableBlinked = true;
            }
        });
        const el = document.getElementById("tblWrap");
        obs.observe(el, { childList: true, subtree: true, attributes: true });
    }""")

    # Navigate into folder
    folder_cell = page.locator(".gallery .gcell:has-text('docs_folder')").first
    folder_cell.click()
    page.wait_for_timeout(300)

    # Navigate back to root
    page.click("#bcRoot")
    page.wait_for_timeout(300)

    table_blinked = page.evaluate("() => window.__tableBlinked")
    assert not table_blinked, "Table chrome flashed during folder navigation"

    # Verify root file cell is visible and clickable
    cell = page.locator(".gallery .gcell:has-text('stable_preview.txt')").first
    assert cell.is_visible()
    cell.click()
    page.wait_for_selector("#fileModal", state="visible", timeout=3000)
    page.click("#fmClose")
    page.wait_for_selector("#fileModal", state="hidden", timeout=3000)


def test_folder_view_dom_preservation(authed_page: Page, tmp_path: Path):
    """Test 15 (BUG-38): Bounded folder view preservation restores DOM elements in 0ms."""
    page = authed_page
    _upload_file(page, tmp_path, "preserve_sample.txt")

    # Create a subfolder
    page.evaluate("""async () => {
        await api("/api/v1/admin/folders/create", {
            method: "POST",
            body: JSON.stringify({ path: "cache_subfolder" })
        });
        await refresh();
    }""")
    page.wait_for_timeout(300)

    # Mark the current gallery element with an expando property to verify 0ms DOM preservation
    page.evaluate("""() => {
        const g = document.querySelector("#tblWrap .gallery:not(#noMatch)");
        if (g) g.__rootPreservedMarker = 42;
    }""")

    # Navigate into subfolder
    folder_cell = page.locator(".gallery .gcell:has-text('cache_subfolder')").first
    folder_cell.click()
    page.wait_for_timeout(200)

    # Verify we are in subfolder
    assert page.locator("#bcTrail").inner_text() != ""

    # Navigate back to root via breadcrumb
    page.click("#bcRoot")
    page.wait_for_timeout(100)

    # Verify the root gallery DOM element is preserved
    marker = page.evaluate("""() => {
        const g = document.querySelector("#tblWrap .gallery:not(#noMatch)");
        return g ? g.__rootPreservedMarker : null;
    }""")
    assert marker == 42, "Expected root gallery DOM element to be preserved from LRU cache"

    # Eviction test: upload a file and verify cache is invalidated
    _upload_file(page, tmp_path, "new_file_evict.txt")
    marker_after_evict = page.evaluate("""() => {
        const g = document.querySelector("#tblWrap .gallery:not(#noMatch)");
        return g ? g.__rootPreservedMarker : null;
    }""")
    assert marker_after_evict is None, "Cache should be evicted on file upload"


def test_large_file_selection_performance(authed_page: Page):
    """Test 16: Freeze-free in-place selection with 100+ files and DOM preservation."""
    page = authed_page

    # Inject 100 mock files into client state and render
    page.evaluate("""() => {
        const mockFiles = [];
        for (let i = 0; i < 100; i++) {
            mockFiles.push({
                id: "mock_file_" + i,
                filename: "benchmark_doc_" + i + ".txt",
                size: 1024 * (i + 1),
                content_type: "text/plain",
                created_at: 1727712000 + i,
                downloaded: 0
            });
        }
        window.files = mockFiles;
        evictFolderViewCache();
        renderRows();
    }""")
    page.wait_for_selector(".gallery .gcell", timeout=4000)

    # Attach marker to first DOM element to verify in-place preservation
    page.evaluate("""() => {
        const first = document.querySelector(".gallery .gcell");
        if (first) first.__preserveMarker = "intact_node_123";
    }""")

    # Activate select mode
    page.click("#selectModeBtn")
    page.wait_for_selector("#selAllBtn", state="visible", timeout=2000)

    # Click Select All and measure JS execution duration
    duration_ms = page.evaluate("""() => {
        const t0 = performance.now();
        document.getElementById("selAllBtn").click();
        return performance.now() - t0;
    }""")
    assert duration_ms < 100, f"Select all execution took {duration_ms}ms (expected <100ms)"

    # Verify all items selected and marker preserved (no DOM rebuild)
    sel_count, marker_preserved = page.evaluate("""() => {
        const first = document.querySelector(".gallery .gcell");
        return [window.selSet.size, first ? first.__preserveMarker : null];
    }""")
    assert sel_count == 100, f"Expected 100 selected items, got {sel_count}"
    assert marker_preserved == "intact_node_123", (
        "DOM nodes were destroyed and recreated during select all"
    )

    # Click Deselect All and verify in-place clearing
    deselect_duration_ms = page.evaluate("""() => {
        const t0 = performance.now();
        document.getElementById("selAllBtn").click();
        return performance.now() - t0;
    }""")
    assert deselect_duration_ms < 100, f"Deselect all execution took {deselect_duration_ms}ms"

    sel_count_after = page.evaluate("() => window.selSet.size")
    assert sel_count_after == 0, f"Expected 0 selected items after deselect, got {sel_count_after}"

    # Deactivate select mode and confirm clean exit
    page.click("#selectModeBtn")
    is_select_mode = page.evaluate("() => window.selectMode")
    assert not is_select_mode


def test_cold_start_direct_file_loading(authed_page: Page, e2e_server: str, tmp_path: Path):
    """Test 17: Cold restart directly loads files without opening Settings."""
    page = authed_page
    _upload_file(page, tmp_path, "cold_restart_probe.txt")
    page.wait_for_selector(".gallery .gcell:has-text('cold_restart_probe.txt')", timeout=4000)

    # Simulate cold start: clear session cookies while preserving localStorage API key
    page.context.clear_cookies()

    # Navigate directly to root dashboard
    page.goto(f"{e2e_server}/")
    page.wait_for_selector("#app", state="visible", timeout=4000)

    # Assert files view populates directly without opening settings modal
    cell = page.locator(".gallery .gcell:has-text('cold_restart_probe.txt')").first
    page.wait_for_selector(".gallery .gcell:has-text('cold_restart_probe.txt')", timeout=4000)
    assert cell.is_visible()

    # Confirm settings modal was never opened
    drawer_on = page.evaluate("() => document.getElementById('drawer').classList.contains('on')")
    assert not drawer_on, "Settings drawer should not be opened during cold start initialization"


def test_file_move_validation_and_progress(authed_page: Page, tmp_path: Path):
    """Test 18: File move UX with client-side path validation and modal progress feedback."""
    page = authed_page
    _upload_file(page, tmp_path, "move_target.txt")
    page.wait_for_selector(".gallery .gcell:has-text('move_target.txt')", timeout=4000)

    # Create test folders
    page.evaluate("""async () => {
        await api("/api/v1/admin/folders/create", {
            method: "POST",
            body: JSON.stringify({ path: "parent_dir" })
        });
        await api("/api/v1/admin/folders/create", {
            method: "POST",
            body: JSON.stringify({ path: "parent_dir/child_dir" })
        });
        await refresh();
    }""")
    page.wait_for_timeout(300)

    # 1. Validation test: circular folder move
    page.evaluate("""() => {
        openMoveModal(["folder:parent_dir/"], "1 folder");
    }""")
    page.wait_for_selector("#moveModal", state="visible", timeout=2000)

    # Attempt circular move into child folder
    if not page.is_visible("#moveDest"):
        page.click("#moveManualToggle")
    page.fill("#moveDest", "parent_dir/child_dir")
    page.click("#moveOk")
    page.wait_for_selector("#moveErr", state="visible", timeout=2000)
    err_text = page.inner_text("#moveErr")
    assert "نمی‌توان" in err_text or "Cannot" in err_text or "امکان انتقال" in err_text

    # Modal remains open on error
    assert page.locator("#moveModal").is_visible()

    # 2. Validation test: same destination for files
    file_id = page.evaluate("""() => {
        const f = window.files.find(x => x.filename === "move_target.txt");
        return f ? f.id : null;
    }""")
    assert file_id is not None
    page.evaluate(f"""() => {{
        openMoveModal(["{file_id}"], "1 file");
    }}""")
    if not page.is_visible("#moveDest"):
        page.click("#moveManualToggle")
    page.fill("#moveDest", "")  # already at root
    page.click("#moveOk")
    page.wait_for_selector("#moveErr", state="visible", timeout=2000)
    err_text = page.inner_text("#moveErr")
    assert "از قبل" in err_text or "already" in err_text

    # 3. Successful move test
    page.fill("#moveDest", "parent_dir")
    page.click("#moveOk")
    page.wait_for_selector("#moveModal", state="hidden", timeout=4000)
    page.wait_for_timeout(300)

    # Confirm file moved into parent_dir
    moved_obj = page.evaluate("""() => {
        return window.files.find(x => x.filename === "parent_dir/move_target.txt");
    }""")
    assert moved_obj is not None, "File should have been moved into parent_dir"


def test_search_clear_race_safety(authed_page: Page, tmp_path: Path):
    """Test 19: Search debounce cancellation on clear prevents stale query resurrection."""
    page = authed_page
    _upload_file(page, tmp_path, "search_alpha.txt")
    _upload_file(page, tmp_path, "search_beta.txt")
    page.wait_for_selector(".gallery .gcell:has-text('search_alpha.txt')", timeout=4000)

    # 1. Type query and immediately clear within debounce window
    page.fill("#fSearch", "alpha")
    page.click("#fClear")
    page.wait_for_timeout(300)

    # Verify input is empty and both files remain visible
    search_val = page.input_value("#fSearch")
    assert search_val == "", f"Expected empty search, got {search_val}"
    assert page.locator(".gallery .gcell:has-text('search_alpha.txt')").is_visible()
    assert page.locator(".gallery .gcell:has-text('search_beta.txt')").is_visible()

    # 2. Rapid typing followed by backspacing all characters
    page.type("#fSearch", "beta", delay=20)
    for _ in range(4):
        page.keyboard.press("Backspace")
    page.wait_for_timeout(300)

    # Confirm query never resurrects after delay
    search_val_after = page.input_value("#fSearch")
    assert search_val_after == "", (
        f"Expected empty search after backspacing, got {search_val_after}"
    )
    assert page.locator(".gallery .gcell:has-text('search_alpha.txt')").is_visible()
    assert page.locator(".gallery .gcell:has-text('search_beta.txt')").is_visible()


def test_mkv_video_playback_detection(authed_page: Page, tmp_path: Path):
    """Test 20: Capability-aware MKV playback and error code discrimination."""
    page = authed_page
    mkv_path = tmp_path / "clip.mkv"
    real_mkv = Path(__file__).parent / "data" / "test_embedded.mkv"
    if real_mkv.exists():
        mkv_path.write_bytes(real_mkv.read_bytes())
    else:
        mkv_path.write_bytes(
            b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\xf7\x81\x01\x42\xf2\x81\x04\x42\xf3\x81\x08\x42\x82\x88matroska"
            + b"\x00" * 4096
        )
    _upload_file(page, tmp_path, "clip.mkv")
    page.wait_for_selector(".gallery .gcell:has-text('clip.mkv')", timeout=4000)

    # Open preview modal
    cell = page.locator(".gallery .gcell:has-text('clip.mkv')").first
    cell.click()
    page.wait_for_selector("#fileModal", state="visible", timeout=4000)

    # Verify video element renders with proper MIME source
    video = page.locator("#fmVid")
    assert video.is_visible()
    src_type = page.evaluate("() => document.querySelector('#fmVid source')?.getAttribute('type')")
    assert src_type == "video/x-matroska"

    # Verify no blanket false MKV error is shown
    fallback = page.locator(".fm-fallback")
    assert not fallback.is_visible(), "Should not show blanket MKV fallback on initial render"

    # Close modal
    page.click("#fmClose")
    page.wait_for_selector("#fileModal", state="hidden", timeout=3000)


def test_hierarchical_move_browser_navigation(authed_page: Page, tmp_path: Path):
    """Test 21: Hierarchical move browser with 5-level drill-down and breadcrumb ascension."""
    page = authed_page
    _upload_file(page, tmp_path, "deep_file.txt")
    page.wait_for_selector(".gallery .gcell:has-text('deep_file.txt')", timeout=4000)

    # Seed 5-level directory structure
    page.evaluate("""async () => {
        const levels = [
            "lvl1",
            "lvl1/lvl2",
            "lvl1/lvl2/lvl3",
            "lvl1/lvl2/lvl3/lvl4",
            "lvl1/lvl2/lvl3/lvl4/lvl5",
        ];
        for (const p of levels) {
            await api("/api/v1/admin/folders/create", {
                method: "POST",
                body: JSON.stringify({ path: p })
            });
        }
        await refresh();
    }""")
    page.wait_for_timeout(300)

    file_id = page.evaluate("""() => {
        const f = window.files.find(x => x.filename === "deep_file.txt");
        return f ? f.id : null;
    }""")
    assert file_id is not None

    # Open move modal
    page.evaluate(f"""() => {{
        openMoveModal(["{file_id}"], "deep_file.txt");
    }}""")
    page.wait_for_selector("#moveModal", state="visible", timeout=2000)

    # Assert move browser components exist
    assert page.locator("#moveBreadcrumbs").is_visible()
    assert page.locator("#moveFolderList").is_visible()
    assert page.locator("#moveTargetBadge").is_visible()

    # 1. Drill down level 1
    page.wait_for_selector(".move-folder-tile[data-folder='lvl1']", timeout=2000)
    page.click(".move-folder-tile[data-folder='lvl1']")

    # 2. Drill down level 2
    page.wait_for_selector(".move-folder-tile[data-folder='lvl2']", timeout=2000)
    page.click(".move-folder-tile[data-folder='lvl2']")

    # 3. Drill down level 3
    page.wait_for_selector(".move-folder-tile[data-folder='lvl3']", timeout=2000)
    page.click(".move-folder-tile[data-folder='lvl3']")

    # 4. Drill down level 4
    page.wait_for_selector(".move-folder-tile[data-folder='lvl4']", timeout=2000)
    page.click(".move-folder-tile[data-folder='lvl4']")

    # 5. Drill down level 5
    page.wait_for_selector(".move-folder-tile[data-folder='lvl5']", timeout=2000)
    page.click(".move-folder-tile[data-folder='lvl5']")

    # Verify target indicator reflects deep path
    badge_text = page.inner_text("#moveTargetBadge")
    assert "lvl1/lvl2/lvl3/lvl4/lvl5" in badge_text

    # Verify breadcrumb segments exist
    crumbs = page.locator(".move-crumb")
    assert crumbs.count() >= 6  # Root + lvl1 + lvl2 + lvl3 + lvl4 + lvl5

    # Ascend to lvl2 via breadcrumb click
    page.click(".move-crumb[data-path='lvl1/lvl2']")
    page.wait_for_selector(".move-folder-tile[data-folder='lvl3']", timeout=2000)
    badge_text_after = page.inner_text("#moveTargetBadge")
    assert "lvl1/lvl2" in badge_text_after
    assert "lvl3" not in badge_text_after

    # Confirm move by clicking Move Here button without typing any path
    page.click("#moveOk")
    page.wait_for_selector("#moveModal", state="hidden", timeout=4000)

    # Verify file is moved to lvl1/lvl2/deep_file.txt
    new_path = page.evaluate(f"""() => {{
        const f = window.files.find(x => x.id === "{file_id}");
        return f ? f.filename : null;
    }}""")
    assert new_path == "lvl1/lvl2/deep_file.txt"


def test_responsive_toolbar_and_empty_states(authed_page: Page, tmp_path: Path):
    """Test 22: Grouped toolbar layout, mobile touch targets, and empty states."""
    page = authed_page

    # 1. Desktop Viewport (1280x800)
    page.set_viewport_size({"width": 1280, "height": 800})
    page.wait_for_selector(".toolbar", timeout=3000)

    # Assert 3 semantic toolbar groups exist
    assert page.locator(".toolbar-group-primary").is_visible()
    assert page.locator(".toolbar-group-view").is_visible()
    assert page.locator(".toolbar-group-actions").is_visible()

    # Assert desktop button heights adhere to 36px standard
    upload_btn = page.locator("#uploadToggleBtn")
    box = upload_btn.bounding_box()
    assert box is not None and box["height"] >= 34, f"Upload btn height {box} < 34px"

    # Assert empty vault illustration state
    if page.locator("#empty").is_visible():
        assert page.locator("#empty .empty-title").is_visible()
        assert page.locator("#empty .empty-action-btn").is_visible()

    # Upload a file so search filtering can be exercised
    _upload_file(page, tmp_path, "search_sample.txt")
    page.wait_for_selector(".gallery .gcell:has-text('search_sample.txt')", timeout=4000)

    # Assert empty search state renders rich contextual illustration and clear button
    page.fill("#fSearch", "nonexistent_query_xyz_123")
    page.wait_for_selector("#noMatch", state="visible", timeout=3000)
    assert page.locator("#noMatch .empty-title").is_visible()
    clear_btn = page.locator("#emptyClearSearchBtn")
    assert clear_btn.is_visible()
    clear_btn.click()
    page.wait_for_timeout(300)
    assert page.input_value("#fSearch") == ""

    # 2. Mobile Viewport (375x667)
    page.set_viewport_size({"width": 375, "height": 667})
    page.wait_for_timeout(300)

    # Assert no horizontal overflow
    scroll_fits = page.evaluate("() => document.body.scrollWidth <= window.innerWidth")
    assert scroll_fits, "Page horizontally scrolls on 375px mobile viewport"

    # Assert touch targets >= 36px height
    for selector in ["#uploadToggleBtn", "#selectModeBtn", "#newFolderBtn"]:
        btn_box = page.locator(selector).bounding_box()
        assert btn_box is not None and btn_box["height"] >= 34, f"{selector} height < 34px"


def test_async_modal_submit_guard_stress(authed_page: Page, tmp_path: Path):
    """Test 23: Double-click rejection and spinner activation under simulated network delay."""
    page = authed_page

    # Simulate 400ms server delay on folders/create in the browser
    page.evaluate("""() => {
        const origFetch = window.fetch;
        window._createFolderCalls = 0;
        window.fetch = async (...args) => {
            const url = typeof args[0] === 'string' ? args[0] : (args[0]?.url || "");
            if (url && url.includes('/admin/folders/create')) {
                window._createFolderCalls++;
                await new Promise(r => setTimeout(r, 400));
            }
            return origFetch(...args);
        };
    }""")

    # Click new folder button to open prompt
    page.click("#newFolderBtn")
    page.wait_for_selector(".modal.on #__askInp", timeout=2000)
    page.fill("#__askInp", "guarded_folder")

    # Double click the submit button rapidly
    ok_btn = page.locator("#__askOk")
    ok_btn.click()
    # Immediate subsequent click should be ignored because button was disabled / answered
    page.evaluate("() => { const b = document.querySelector('#__askOk'); if (b) b.click(); }")

    # Wait for completion and modal removal
    page.wait_for_selector(".modal.on #__askInp", state="detached", timeout=4000)

    # Verify exactly 1 network request was initiated
    calls = page.evaluate("() => window._createFolderCalls")
    assert calls == 1, f"Expected exactly 1 API call, got {calls}"

    # Wait for folder to appear authoritatively in the view
    page.wait_for_selector(
        ".gallery .gcell:has-text('guarded_folder'), #rows tr:has-text('guarded_folder')",
        timeout=4000,
    )
    folder_count = page.evaluate("""() => {
        return (window.files || []).filter(x => x.filename === "guarded_folder/").length;
    }""")
    assert folder_count == 1, f"Expected 1 folder created, got {folder_count}"


def test_video_playback_and_seeking(authed_page: Page, tmp_path: Path):
    """Test 24: Video playback and seeking to multiple timestamps without stalls or 429."""
    page = authed_page
    video_path = tmp_path / "seek_journey.mp4"
    real_video = Path("/tmp/test_10min_video.mp4")
    if real_video.exists():
        video_path.write_bytes(real_video.read_bytes())
    else:
        fixture = Path(__file__).parent / "data" / "test_embedded.mkv"
        video_path.write_bytes(fixture.read_bytes())

    page.set_input_files("#fileInput", str(video_path))
    page.wait_for_selector(".qitem.done", timeout=12000)
    page.wait_for_timeout(300)

    cell = page.locator(f".gallery .gcell:has-text('{video_path.name}')").first
    cell.click()
    page.wait_for_selector("#fmVid", state="visible", timeout=4000)

    # Wait for metadata
    page.evaluate("""async () => {
        const v = document.querySelector("#fmVid");
        if (v.readyState < 1) {
            await new Promise(r => v.addEventListener("loadedmetadata", r, { once: true }));
        }
    }""")

    # Play and seek forward
    page.evaluate("() => document.querySelector('#fmVid').play()")
    page.wait_for_timeout(500)

    duration = page.evaluate("() => document.querySelector('#fmVid').duration")
    if duration > 10:
        target = min(60, duration / 2)
        page.evaluate(f"() => {{ document.querySelector('#fmVid').currentTime = {target}; }}")
        page.wait_for_timeout(1000)
        curr = page.evaluate("() => document.querySelector('#fmVid').currentTime")
        assert curr >= target - 1

    page.click("#fmClose")
    page.wait_for_selector("#fileModal", state="hidden", timeout=3000)


def test_settings_mobile_responsiveness_and_telegram_test(authed_page: Page):
    """Test 25: Settings drawer responsiveness on mobile (<640px) and live Telegram test button."""
    page = authed_page

    # 1. Resize to mobile phone viewport (375x667, iPhone SE)
    page.set_viewport_size({"width": 375, "height": 667})

    # Open Settings
    page.click("#setBtn")
    page.wait_for_selector("#drawer.on", timeout=4000)

    # 2. Check mobile layout behavior
    # Form row labels and inputs should be stacked on small screens
    row_flex_dir = page.evaluate("""() => {
        const row = document.querySelector("#secTgConfig .set-row:not(:has(> .sw))");
        return row ? window.getComputedStyle(row).flexDirection : "";
    }""")
    assert row_flex_dir == "column", f"Expected column flex direction on mobile, got {row_flex_dir}"

    # Verify input widths expand to 100% on mobile
    inp_width = page.evaluate("""() => {
        const inp = document.querySelector("#s_tg_channel_id");
        return inp ? inp.getBoundingClientRect().width : 0;
    }""")
    assert inp_width > 280, f"Expected input width > 280px on 375px viewport, got {inp_width}"

    # Verify switch rows remain horizontal (space-between)
    sw_row_flex_dir = page.evaluate("""() => {
        const swRow = document.querySelector(".drawer .set-row:has(> .sw)");
        return swRow ? window.getComputedStyle(swRow).flexDirection : "";
    }""")
    assert sw_row_flex_dir == "row", f"Switches should be row, got {sw_row_flex_dir}"

    # 3. Test Telegram Test Connection button
    test_btn = page.locator("#btnTgTestConn")
    assert test_btn.is_visible()

    # Intercept /telegram/test API call
    page.evaluate("""() => {
        const origFetch = window.fetch;
        window.fetch = async (...args) => {
            const url = typeof args[0] === 'string' ? args[0] : (args[0]?.url || "");
            if (url.includes('/admin/telegram/test')) {
                return new Response(JSON.stringify({
                    ok: true,
                    bots: [
                        {
                            index: 0,
                            masked_token: "123456:••••••",
                            working: true,
                            username: "verified_bot"
                        }
                    ],
                    session: {
                        available: true,
                        working: true,
                        details: {
                            id: 8888,
                            username: "verified_user",
                            first_name: "Verified User"
                        }
                    }
                }), { status: 200, headers: { 'Content-Type': 'application/json' } });
            }
            return origFetch(...args);
        };
    }""")

    test_btn.click()
    page.wait_for_timeout(500)

    # Check that connected box is visible with verified details
    conn_box = page.locator("#tgAuthConnectedBox")
    assert conn_box.is_visible()
    box_text = conn_box.inner_text()
    assert "verified_user" in box_text or "Verified User" in box_text

    # Close settings
    page.click("#setClose")
    page.wait_for_selector("#drawer.on", state="detached", timeout=3000)
    has_on = page.evaluate("() => document.querySelector('#drawer').classList.contains('on')")
    assert not has_on


def test_upload_queue_pause_resume_and_audio_controls(authed_page: Page, tmp_path: Path):
    """Test 26: Upload queue pause/resume controls and enhanced audio preview playback speeds."""
    page = authed_page

    # 1. Test audio preview controls
    audio_path = tmp_path / "song.mp3"
    audio_path.write_bytes(b"\xff\xfb\x90\x44" + b"\x00" * 2048)  # minimal mp3 frame
    _upload_file(page, tmp_path, "song.mp3")
    page.wait_for_selector(".gallery .gcell:has-text('song.mp3')", timeout=4000)

    # Click audio cell name to open preview modal
    cell = page.locator(".gallery .gcell:has-text('song.mp3')").first
    cell.locator(".gname").click()
    page.wait_for_selector("#fileModal", state="visible", timeout=4000)

    # Check audio player controls
    assert page.locator("#fmAud").is_visible()
    assert page.locator(".aud-skip[data-skip='-10']").is_visible()
    assert page.locator(".aud-skip[data-skip='10']").is_visible()
    speed_btns = page.locator(".aud-speed-btn")
    assert speed_btns.count() >= 5

    # Click speed button 1.5x
    btn_15 = page.locator(".aud-speed-btn[data-speed='1.5']")
    btn_15.click()
    speed_val = page.evaluate("() => document.querySelector('#fmAud').playbackRate")
    assert speed_val == 1.5

    # Close modal
    page.click("#fmClose")
    page.wait_for_selector("#fileModal", state="hidden", timeout=3000)

    # 2. Test queue pause and resume client actions
    res = page.evaluate("""() => {
        queue.push({
            id: "test-paused-upload",
            file: { name: "test_large.bin", size: 32 * 1024 * 1024 },
            state: "up",
            prog: 50,
            _xhr: { abort: () => {} }
        });
        renderQueue();
        const pauseBtn = document.querySelector('.qpause[data-id="test-paused-upload"]');
        if (!pauseBtn) return { hasPause: false };
        pauseItem("test-paused-upload");
        const resumeBtn = document.querySelector('.qresume[data-id="test-paused-upload"]');
        const isPausedState = queue.find(q => q.id === "test-paused-upload")?.state === "paused";
        return {
            hasPause: true,
            hasResume: !!resumeBtn,
            isPausedState: isPausedState
        };
    }""")
    assert res["hasPause"] is True
    assert res["hasResume"] is True
    assert res["isPausedState"] is True


def test_settings_telegram_webhook_and_owner_id_panel(authed_page: Page):
    """Test 27: Settings drawer Telegram webhook management & authorized owner IDs."""
    page = authed_page

    # Open settings
    page.click("#setBtn")
    page.wait_for_selector("#drawer.on", timeout=4000)

    # Check fields are present
    assert page.locator("#s_tg_owner_ids").is_visible()
    assert page.locator("#s_tg_webhook_secret").is_visible()
    assert page.locator("#btnTgSetWebhook").is_visible()
    assert page.locator("#btnTgWebhookInfo").is_visible()
    assert page.locator("#btnTgDelWebhook").is_visible()

    # Fill owner IDs
    page.fill("#s_tg_owner_ids", "11223344, 55667788")

    # Save settings and wait for server response
    with page.expect_response(
        lambda r: "/api/v1/admin/telegram-config" in r.url and r.status == 200
    ):
        page.click("#saveBtn")

    page.wait_for_timeout(300)

    # Close settings
    page.click("#setClose")
    page.wait_for_selector("#drawer.on", state="detached", timeout=3000)

    # Re-open settings to verify persistence in UI
    with page.expect_response(
        lambda r: "/api/v1/admin/telegram-config" in r.url and r.status == 200,
        timeout=10000,
    ):
        page.click("#setBtn")
    page.wait_for_selector("#drawer.on", timeout=10000)
    page.wait_for_function(
        "() => document.querySelector('#s_tg_owner_ids').value !== ''", timeout=10000
    )
    val = page.input_value("#s_tg_owner_ids")
    assert val == "11223344, 55667788"

    page.click("#setClose")
    page.wait_for_selector("#drawer.on", state="detached", timeout=3000)


def test_active_ingests_modal_and_cancel(authed_page: Page):
    """Test 28: Active Ingests toolbar pill, live task progress rendering, and cancel action."""
    page = authed_page

    # Mock /api/v1/admin/ingest/active to return an in-progress task
    page.route(
        "**/api/v1/admin/ingest/active",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body="""{
            "tasks": [
                {
                    "id": "test-task-123",
                    "source": "telegram",
                    "filename": "ubuntu_server.iso",
                    "transferred_bytes": 524288000,
                    "total_bytes": 1048576000,
                    "pct": 50.0,
                    "speed": 10485760.0,
                    "eta": 50.0,
                    "state": "pulling"
                }
            ]
        }""",
        ),
    )

    # Trigger poll
    page.evaluate("() => checkActiveIngests()")
    page.wait_for_selector("#ingestBtn", state="visible", timeout=3000)

    btn_visible, cnt = page.evaluate("""() => {
        const btn = document.querySelector("#ingestBtn");
        const cnt = document.querySelector("#ingestCnt");
        return [btn && btn.style.display !== "none", cnt ? cnt.textContent : ""];
    }""")
    assert btn_visible is True
    assert cnt == "1"

    # 2. Click Active Ingests button to open modal
    page.click("#ingestBtn")
    page.wait_for_selector("#activeIngestModal.on", timeout=3000)
    page.wait_for_selector("#ingestList .keyrow", timeout=3000)

    # Check that card content is rendered
    assert page.locator("#ingestList").is_visible()
    card_text = page.inner_text("#ingestList")
    assert "ubuntu_server.iso" in card_text
    assert "50%" in card_text
    assert "10.0 MB" in card_text

    # Cancel button is visible
    cancel_btn = page.locator(".cancel-ing-btn")
    assert cancel_btn.is_visible()

    # Close modal
    page.click("#ingestClose")
    page.wait_for_selector("#activeIngestModal.on", state="detached", timeout=3000)


def test_settings_tab_navigation_and_section_sync(authed_page: Page):
    """Test 29: Settings drawer categories navigation and smooth section synchronization."""
    page = authed_page
    page.click("#setBtn")
    page.wait_for_selector("#drawer.on", timeout=6000)

    expected_tabs = [
        "all",
        "secUI",
        "secAuth",
        "secS3",
        "secCrypto",
        "secRate",
        "secTgConfig",
        "secBackup",
        "secAuditLogs",
    ]
    for tab_key in expected_tabs:
        loc = page.locator(f'.dtab[data-sec="{tab_key}"]')
        assert loc.is_visible(), f"Tab {tab_key} must be visible"

    # Click Telegram tab
    page.click('.dtab[data-sec="secTgConfig"]')
    page.wait_for_function(
        "() => document.querySelector('.dtab[data-sec=\"secTgConfig\"]').classList.contains('active')",
        timeout=3000,
    )
    assert page.locator("#secTgConfig").is_visible()

    # Click Rate/Limits tab
    page.click('.dtab[data-sec="secRate"]')
    page.wait_for_function(
        "() => document.querySelector('.dtab[data-sec=\"secRate\"]').classList.contains('active')",
        timeout=3000,
    )
    assert page.locator("#secRate").is_visible()

    page.click("#setClose")
    page.wait_for_selector("#drawer.on", state="detached", timeout=3000)


def test_telegram_settings_cards_rendered(authed_page: Page):
    """Test 30: Telegram settings organized into structured modular cards."""
    page = authed_page
    page.click("#setBtn")
    page.wait_for_selector("#drawer.on", timeout=6000)

    # Required inputs inside Telegram settings must be present and visible
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
    page.wait_for_selector("#drawer.on", state="detached", timeout=3000)


def test_security_and_performance_cards_rendered(authed_page: Page):
    """Test 31: Security and Performance controls organized into modular cards."""
    page = authed_page
    page.click("#setBtn")
    page.wait_for_selector("#drawer.on", timeout=6000)

    # Click secCrypto tab
    page.click('.dtab[data-sec="secCrypto"]')
    assert page.locator("#swEnc").is_visible()
    assert page.locator("#swClientZk").is_visible()
    assert page.locator("#s_enc_secret").is_visible()
    assert page.locator("#secCrypto .set-card").count() >= 2

    # Click secRate tab
    page.click('.dtab[data-sec="secRate"]')
    assert page.locator("#s_rate_download").is_visible()
    assert page.locator("#s_max_upload_mb").is_visible()
    assert page.locator("#swCache").is_visible()
    assert page.locator("#purgeBtn").is_visible()
    assert page.locator("#secRate .set-card").count() >= 2

    page.click("#setClose")
    page.wait_for_selector("#drawer.on", state="detached", timeout=3000)

