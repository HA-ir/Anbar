"""v0.15.56 regression tests: hash toggle cycle + softer light theme (BUG-50).

Covers:
- the toggle caches the revealed hash and never re-fetches when cached
- double-clicks during the initial fetch cannot corrupt the field state
- hiding restores the blank field without losing the cached raw hash
- the light theme uses the softened slate/zinc surface palette
- the version bump is consistent across the package and project metadata
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path("src/anbar/ui/index.html").read_text(encoding="utf-8")
INIT = Path("src/anbar/__init__.py").read_text(encoding="utf-8")
PYPROJECT = Path("pyproject.toml").read_text(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
UVLOCK = (ROOT / "uv.lock").read_text(encoding="utf-8")


def _toggle_handler() -> str:
    match = re.search(
        r'let _tgApiHashRaw=""[\s\S]*?'
        r'\$\("#s_tg_hash_toggle"\)\.onclick=(?:async)?\(\)=>\{([\s\S]*?)\n\};',
        SRC,
    )
    assert match, "hash toggle handler not found"
    return match.group(1)


def test_hash_toggle_caches_raw_value():
    handler = _toggle_handler()
    assert "if(_tgApiHashBusy)return;" in handler
    assert 'if(_tgApiHashRaw){\n        inp.type="text";' in handler
    assert "reveal-api-hash" in handler
    fetch_before_cache = handler.index("if(_tgApiHashRaw){")
    fetch_call = handler.index("reveal-api-hash")
    assert fetch_before_cache < fetch_call, "cached reveal must bypass the API fetch"


def test_hash_toggle_hides_cleanly():
    handler = _toggle_handler()
    assert 'inp.type="password";' in handler
    assert 'if(typed===_tgApiHashRaw)inp.value="";' in handler


def test_softened_light_theme_tokens():
    expected = {
        "--bg-canvas": "#e5e7eb",
        "--bg-surface": "#f8fafc",
        "--bg-subtle": "#e2e8f0",
        "--bg-hover": "#cbd5e1",
        "--border-subtle": "#cbd5e1",
        "--border-strong": "#94a3b8",
        "--tx-primary": "#0f172a",
        "--tx-secondary": "#334155",
        "--tx-muted": "#64748b",
    }
    root_block = re.search(r":root\s*\{(.*?)\n\}", SRC, re.S)
    assert root_block, ":root token block not found"
    for token, value in expected.items():
        assert f"{token}: {value};" in root_block.group(1), f"{token} must be {value}"


def test_version_bumped_to_0_15_56():
    assert '__version__ = "0.15.56"' in INIT
    assert 'version = "0.15.56"' in PYPROJECT

def test_uv_lock_version_bumped_to_0_15_56():
    assert 'version = "0.15.56"' in UVLOCK
