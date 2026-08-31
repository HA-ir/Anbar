"""Loop #8: log/audit secret-leakage sweep.

Every log_audit call site must not record plaintext secrets: passwords,
bearer keys, bot tokens, HMAC secrets, or session strings.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path("src/anbar")

# fragile but effective: find log_audit( ... ) call arguments and check the
# literal fragments they log against known secret-bearing variable names
SECRETISH = re.compile(
    r"password|passwd|secret|token|session|api_hash|hmac|admin_key|api_key|bearer",
    re.IGNORECASE,
)


def _log_audit_calls() -> list[tuple[str, str]]:
    out = []
    for py in SRC.rglob("*.py"):
        text = py.read_text()
        for m in re.finditer(r"log_audit\((.*?)\)\n", text, re.S):
            args = " ".join(m.group(1).split())
            out.append((str(py), args))
    return out


def test_audit_calls_never_log_secret_values():
    """No log_audit call may pass a secret-named variable as a logged value.

    Allowed: boolean flags like custom=bool(custom) or auth_enabled — names
    are fine, values are not. We flag calls that interpolate a secret-named
    *variable* (f-string {phone} style is checked manually below).
    """
    offenders = []
    for path, args in _log_audit_calls():
        # secret-named variables interpolated into details/target strings
        safe = re.search(r"bool\(|_enabled|_protected|\.strip\(\) ==|custom", args)
        if SECRETISH.search(args) and not safe:
            offenders.append((path, args))
    assert not offenders, offenders


def test_known_risky_sites_are_safe():
    """The two sites that handle secrets log only derived/safe values."""
    admin = (Path(__file__).parent.parent / "src" / "anbar" / "api" / "admin.py").read_text()
    # telegram MTProto login logs the phone number, never the password/session
    m = re.search(r"log_audit\(\s*\"auth\.telegram_mtproto\".*?details=\{([^}]*)\}", admin, re.S)
    assert m, "telegram_mtproto audit call missing"
    assert "password" not in m.group(1)
    assert "final_session" not in m.group(1)
    # secret rotation logs whether a custom secret was used, not the secret
    m2 = re.search(r"log_audit\(\s*\"secret\.rotate\".*?details=\{([^}]*)\}", admin, re.S)
    assert m2, "secret.rotate audit call missing"
    assert "custom" in m2.group(1) and "secret=" not in m2.group(1)


def test_no_print_debug_of_secrets():
    """No print() of key/token/password variables anywhere in src."""
    offenders = []
    for py in SRC.rglob("*.py"):
        for i, line in enumerate(py.read_text().splitlines(), 1):
            if re.search(r"print\(.*(" + SECRETISH.pattern + r")", line):
                offenders.append(f"{py}:{i}: {line.strip()}")
    assert not offenders, offenders
