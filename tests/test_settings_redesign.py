"""Tests for BUG-42: Settings navigation desktop view redesign."""

import re
from pathlib import Path

SRC = Path("src/anbar/ui/index.html").read_text(encoding="utf-8")


def test_desktop_modal_css():
    # Centered modal dimensions and layout
    assert "min(960px, 92vw)" in SRC or "min(960px,92vw)" in SRC
    assert "min(720px, 88vh)" in SRC or "min(720px,88vh)" in SRC
    assert "border-radius:16px" in SRC or "border-radius: 16px" in SRC
    # Two-column layout grid
    assert "grid-template-columns:240px 1fr" in SRC or "grid-template-columns: 240px 1fr" in SRC
    assert '"head head" "nav body" "nav foot"' in SRC or '"head head"\\n "nav body"' in SRC


def test_sidebar_categories_present_with_icons():
    categories = [
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
    for cat in categories:
        pattern = rf'<button type="button" class="dtab[^"]*" data-sec="{cat}">'
        assert re.search(pattern, SRC), f"Missing dtab button for {cat}"

    # Verify each dtab has an SVG icon
    pattern_dtab = r'<button type="button" class="dtab[^"]*" data-sec="([^"]+)">([\s\S]*?)</button>'
    dtabs = re.findall(pattern_dtab, SRC)
    assert len(dtabs) == 9
    for sec, content in dtabs:
        assert "<svg" in content, f"dtab {sec} is missing SVG icon"
        assert "<span" in content, f"dtab {sec} is missing label span"


def test_category_section_ids():
    expected_ids = [
        "secUI",
        "secAuth",
        "secS3",
        "secCrypto",
        "secRate",
        "secTgConfig",
        "secBackup",
        "secAuditLogs",
    ]
    for eid in expected_ids:
        assert f'id="{eid}"' in SRC, f'Missing id="{eid}" on section element'


def test_scrollspy_js_present():
    assert "setActiveTab" in SRC
    assert "scrollTicking" in SRC or "_scrollTicking" in SRC
    evt1 = '_drawerBody.addEventListener("scroll"'
    evt2 = "_drawerBody.addEventListener('scroll'"
    assert evt1 in SRC or evt2 in SRC


def test_mobile_compatibility():
    # Base drawer class exists with translateX for mobile
    assert "translateX(var(--sx,100%))" in SRC
    # dtab pill style on mobile
    assert "border-radius:20px" in SRC or "border-radius: 20px" in SRC
