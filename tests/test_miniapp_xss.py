"""Repro: miniapp renderList injects f.filename into innerHTML unescaped.

The miniapp fetches /api/v1/admin/objects (admin-gated) and renders:
    `<div class="file-name">${f.filename || f.id}</div>`
A filename containing HTML executes in the Telegram webview session.
"""

import re

MINIAPP = open("src/anbar/ui/miniapp.html", encoding="utf-8").read()


def test_miniapp_escapes_filename_in_render():
    # The template must not interpolate f.filename raw into innerHTML.
    # It must go through an escape helper (esc / escapeHtml / escape).
    assert re.search(r"\$\{\s*esc(Html)?\(\s*f\.filename", MINIAPP), (
        "miniapp renderList must escape f.filename before innerHTML"
    )


def test_miniapp_has_escape_helper():
    assert "const esc = s =>" in MINIAPP, (
        "miniapp must define an HTML escape helper"
    )
