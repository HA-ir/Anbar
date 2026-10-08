"""v0.15.60 release verification tests."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = (ROOT / "src" / "anbar" / "__init__.py").read_text()
PYPROJECT = (ROOT / "pyproject.toml").read_text()
UVLOCK = (ROOT / "uv.lock").read_text()


def test_version_bumped_to_0_15_60():
    assert '__version__ = "0.15.60"' in INIT
    assert 'version = "0.15.60"' in PYPROJECT


def test_uv_lock_version_bumped_to_0_15_60():
    assert 'name = "anbar"\nversion = "0.15.60"' in UVLOCK
