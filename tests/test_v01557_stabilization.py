"""v0.15.57 regression and stabilization tests (BUG-38 to BUG-42)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = (ROOT / "src" / "anbar" / "__init__.py").read_text()
PYPROJECT = (ROOT / "pyproject.toml").read_text()
UVLOCK = (ROOT / "uv.lock").read_text()
INDEX_HTML = (ROOT / "src" / "anbar" / "ui" / "index.html").read_text()


def test_version_bumped_to_0_15_57():
    import re

    assert re.search(r'__version__ = "0\.15\.(57|58)"', INIT)
    assert re.search(r'version = "0\.15\.(57|58)"', PYPROJECT)


def test_uv_lock_version_bumped_to_0_15_57():
    import re

    assert re.search(r'name = "anbar"\nversion = "0\.15\.(57|58)"', UVLOCK)


def test_selection_avoids_render_rows_in_index_html():
    """Verify that select-all and deselect in index.html do not call renderRows()."""
    # Look for the #selAllBtn handler
    assert (
        "renderRows()"
        not in INDEX_HTML[
            INDEX_HTML.find('$("#selAllBtn").onclick') : INDEX_HTML.find('$("#selDelBtn")')
        ]
    )


def test_search_clear_cancels_timer_in_index_html():
    """Verify that #fClear.onclick explicitly cancels searchDebounceTimer."""
    clear_handler = INDEX_HTML[
        INDEX_HTML.find('$("#fClear").onclick') : INDEX_HTML.find('$("#fSort")')
    ]
    assert "clearTimeout(searchDebounceTimer)" in clear_handler
    assert "searchDebounceTimer = null" in clear_handler


def test_api_client_implements_401_retry_in_index_html():
    """Verify that api() client implements re-login promise and request retry on 401."""
    api_fn = INDEX_HTML[
        INDEX_HTML.find("async function api(") : INDEX_HTML.find(
            "/* ================= session ================= */"
        )
    ]
    assert "_reLoginPromise" in api_fn
    assert "/ui/login" in api_fn
    assert "reloginOk" in api_fn


def test_mkv_video_config_includes_source_in_index_html():
    """Verify video element in index.html configures explicit source tag with MIME type."""
    assert '<source src="' in INDEX_HTML
    assert "video/x-matroska" in INDEX_HTML
    assert "vEl.error.code" in INDEX_HTML
