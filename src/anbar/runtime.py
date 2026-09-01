"""Runtime-tunable settings (F8).

Operator-adjustable values, persisted in the ``kv`` table so they survive
restarts but never touch the git-controlled ``.env``. A setting present in
kv overrides the env default; deleting the kv row restores the env value.

Every value is validated against a fixed spec (type + inclusive range) —
the API rejects out-of-range input with 422 before anything is written.
"""

from __future__ import annotations

from .db import Database

KV_PREFIX = "cfg_"

# name: (min, max) — all int settings; 0 means "disabled" where meaningful
SPEC = {
    "rate_download": (0, 100_000),  # per (client IP, object) / min
    "rate_upload": (0, 100_000),  # per API key / min
    "rate_login": (0, 10_000),  # per client IP / min
    "max_upload_mb": (1, 102400),  # object size ceiling, MB
    "web_session_ttl": (300, 604_800),  # seconds, max 7 days
    "cache_mb": (0, 8192),  # LRU budget; 0 = cache off
    # mtproto only: extra exported-auth download connections ("FastTelethon").
    # 0 = off (single connection + ranged workers). Admin-toggleable live via
    # POST /admin/settings; higher values raise FloodWait risk.
    "mtproto_export_conns": (0, 8),
    # hybrid mode: when enabled and backend is mtproto, chunks with bot_file_id
    # are downloaded via high-speed Bot CDN with fallback to mtproto.
    "hybrid_enabled": (0, 1),
    # hybrid bot fallback timeout in milliseconds (e.g. 1500 = 1.5s)
    "hybrid_bot_timeout_ms": (200, 30_000),
    # zero-knowledge encryption: 0 = disabled (plain chunks), 1 = enabled (AES-256-GCM)
    "encryption_enabled": (0, 1),
    # download cache master switch: 0 = cache off entirely, 1 = budget governs.
    # Runtime-tunable (v0.15.37) — used to be .env-only (ANBAR_CACHE_ENABLED),
    # which forced a manual .env edit + restart just to turn the cache on.
    "cache_enabled": (0, 1),
    # auto daily database backup to telegram: 0 = disabled, 1 = enabled
    "auto_backup_enabled": (0, 1),
    # PERF-01: RAM budget (MB) for the per-chunk seek micro cache; 0 = off
    "seek_cache_mb": (0, 512),
}


def get_int(db: Database, name: str, default: int) -> int:
    """Effective value: kv override if present, else the env default."""
    raw = db.kv_get(KV_PREFIX + name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:  # corrupted row → treat as unset
        return default


def set_int(db: Database, name: str, value: int) -> int:
    """Validate against SPEC and persist. Returns the stored value."""
    if name not in SPEC:
        raise KeyError(name)
    lo, hi = SPEC[name]
    if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
        raise ValueError(f"{name} must be an int in [{lo}, {hi}]")
    db.kv_set(KV_PREFIX + name, str(value))
    return value


def reset(db: Database, name: str) -> bool:
    """Remove an override (restore the env default). True if removed."""
    if db.kv_get(KV_PREFIX + name) is None:
        return False
    db._conn.execute("DELETE FROM kv WHERE k = ?", (KV_PREFIX + name,))
    db._conn.commit()
    return True


def effective(db: Database, defaults: dict[str, int]) -> dict:
    """Current effective values plus provenance, for the admin API/UI.

    `defaults` maps spec name → env value.
    """
    out = {}
    for name in SPEC:
        raw = db.kv_get(KV_PREFIX + name)
        cur = int(raw) if raw is not None and raw.lstrip("-").isdigit() else defaults[name]
        out[name] = {"value": cur, "default": defaults[name], "overridden": raw is not None}
    return out
