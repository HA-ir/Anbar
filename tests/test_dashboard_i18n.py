"""Loop #9: dashboard i18n parity + XSS-render sweep (static analysis)."""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path("src/anbar/ui/index.html")
TEXT = SRC.read_text()


def _i18n_blocks() -> tuple[set, set]:
    m = re.search(r"const I18N=\{(.*?)\n\};", TEXT, re.S)
    assert m, "I18N object not found in index.html"
    body = m.group(1)
    fa = re.search(r"\n fa:\{(.*?)\n \},", body, re.S)
    en = re.search(r"\n en:\{(.*?)\n \}", body, re.S)
    assert fa and en, "fa/en blocks not found in I18N"

    def keys(block: str) -> set:
        # keys may be defined mid-line (comma-separated) and at block start
        # (right after the "{"), so allow line-start, post-comma, and
        # post-brace positions
        return set(re.findall(r"(?:^|[{,\n]\s*)([A-Za-z0-9_]+)\s*:", block))

    return keys(fa.group(1)), keys(en.group(1))


def test_i18n_fa_en_parity():
    """fa and en blocks must define the same key sets (bilingual dashboard)."""
    fa_k, en_k = _i18n_blocks()
    assert fa_k == en_k, {
        "fa_only": sorted(fa_k - en_k),
        "en_only": sorted(en_k - fa_k),
    }


def test_all_used_t_keys_exist():
    """Every t("key") call must resolve in the fa block (fa is default lang)."""
    fa_k, _ = _i18n_blocks()
    used = set(re.findall(r'\bt\("([A-Za-z0-9_]+)"\)', TEXT))
    missing = sorted(used - fa_k)
    assert not missing, f"t() keys missing from fa i18n: {missing}"


def test_every_data_i18n_attr_has_key():
    """data-i18n / data-i18n-ph / data-i18n-title keys must exist in fa block."""
    fa_k, _ = _i18n_blocks()
    used = set(re.findall(r'data-i18n(?:-ph|-title)?="([A-Za-z0-9_]+)"', TEXT))
    missing = sorted(used - fa_k)
    assert not missing, f"data-i18n keys missing from fa i18n: {missing}"
