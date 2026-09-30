"""v0.15.58 regression and overhaul verification tests."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = (ROOT / "src" / "anbar" / "__init__.py").read_text()
PYPROJECT = (ROOT / "pyproject.toml").read_text()
UVLOCK = (ROOT / "uv.lock").read_text()
INDEX_HTML = (ROOT / "src" / "anbar" / "ui" / "index.html").read_text()


def test_version_bumped_to_0_15_58():
    assert '__version__ = "0.15.58"' in INIT
    assert 'version = "0.15.58"' in PYPROJECT


def test_uv_lock_version_bumped_to_0_15_58():
    assert 'name = "anbar"\nversion = "0.15.58"' in UVLOCK


def test_design_tokens_defined_in_index_html():
    """Verify that CSS custom properties for buttons and spacing are present in :root."""
    assert "--btn-h: 36px;" in INDEX_HTML
    assert "--btn-h-sm: 30px;" in INDEX_HTML
    assert "--btn-radius: 10px;" in INDEX_HTML
    assert "--sp-xs: 4px;" in INDEX_HTML
    assert "--sp-sm: 8px;" in INDEX_HTML
    assert "--sp-md: 12px;" in INDEX_HTML
    assert "--sp-lg: 16px;" in INDEX_HTML
    assert "--sp-xl: 24px;" in INDEX_HTML


def test_guard_modal_submit_defined_in_index_html():
    """Verify universal guardModalSubmit helper function exists."""
    assert "function guardModalSubmit(btn,fn,opts={})" in INDEX_HTML
    assert 'btn.classList.add("busy")' in INDEX_HTML


def test_move_browser_components_in_index_html():
    """Verify Move modal DOM contains breadcrumbs, child folder viewport, and target badge."""
    assert 'id="moveBreadcrumbs"' in INDEX_HTML
    assert 'id="moveFolderList"' in INDEX_HTML
    assert 'id="moveTargetBadge"' in INDEX_HTML
    assert "function renderMoveBrowser" in INDEX_HTML
    assert "function getAllFolderPaths" in INDEX_HTML


def test_semantic_toolbar_flex_groups_in_index_html():
    """Verify toolbar is structured into primary, view, and action flex groups."""
    assert "toolbar-group-primary" in INDEX_HTML
    assert "toolbar-group-view" in INDEX_HTML
    assert "toolbar-group-actions" in INDEX_HTML


def test_media_teardown_on_fm_close():
    """Verify media playback is stopped and source unloaded on fmClose."""
    start = INDEX_HTML.find('$("#fmClose").onclick')
    end = INDEX_HTML.find('$("#fmCloseTop")')
    fm_close_snippet = INDEX_HTML[start:end]
    assert "vid.pause()" in fm_close_snippet
    assert "vid.removeAttribute" in fm_close_snippet
    assert "vid.load()" in fm_close_snippet
