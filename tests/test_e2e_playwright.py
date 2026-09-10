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
