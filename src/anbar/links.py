"""Share-link registry (v0.10).

Links were previously write-only: mint a signed URL and hope you still have
the message it lives in. This module makes links first-class:

- every mint registers `link:<obj_id>:<exp>` → meta JSON in kv;
- ``list_links`` walks those entries (newest first);
- ``revoke`` deletes the signature tag (`rev:<obj_id>:<exp>`), which
  `_authenticate_download` checks, so the URL dies immediately even though
  its `exp` is still in the future.

Revocation design: signatures are stateless HMAC, so "revoke" adds a small
tombstone check instead of a token store. The tombstone is per-(object,
expiry) — cheap to look up, trivially deleted, and never touches unrelated
links. Password/cap/slug tags are cleaned up when their last link goes.
"""
from __future__ import annotations

import json
import time

KV_PREFIX = "link:"  # link:<obj_id>:<exp> -> {slug?, pw?, max_dl?}
REV_PREFIX = "rev:"  # rev:<obj_id>:<exp> = "1" while revoked


def register_link(db, obj_id: str, exp: int, *, slug: str | None = None,
                  password_protected: bool = False, max_dl: int = 0) -> None:
    """Record a freshly minted link so it can be listed and later revoked."""
    db.kv_set(f"{KV_PREFIX}{obj_id}:{exp}", json.dumps({
        "slug": slug or None,
        "pw": bool(password_protected),
        "max_dl": max_dl or None,
        "created_at": int(time.time()),
    }, separators=(",", ":")))


def is_revoked(db, obj_id: str, exp: int) -> bool:
    return db.kv_get(f"{REV_PREFIX}{obj_id}:{exp}") is not None


def revoke(db, obj_id: str, exp: int) -> bool:
    """Kill one link now. Returns False when the link doesn't exist."""
    key = f"{KV_PREFIX}{obj_id}:{exp}"
    if db.kv_get(key) is None:
        return False
    db.kv_delete(key)
    db.kv_set(f"{REV_PREFIX}{obj_id}:{exp}", "1")
    _cleanup_tags(db, obj_id)
    return True


def list_links(db, limit: int = 200, *, include_dead: bool = False) -> list[dict]:
    """Registered links (newest-expiry first) with object names.

    Default shows **live links only** — revoked and expired ones are hidden
    so the manager reflects what is actually shareable right now. Pass
    `include_dead=True` for an audit view.
    """
    now = int(time.time())
    rows = []
    revoked = {}
    for k, _v in db.kv_all():
        if k.startswith(REV_PREFIX):
            try:
                _, obj_id, exp_s = k.split(":", 2)
                revoked[(obj_id, int(exp_s))] = True
            except ValueError:
                continue
    for k, v in db.kv_all():
        if not k.startswith(KV_PREFIX):
            continue
        try:
            rest = k[len(KV_PREFIX):]
            obj_id, exp_s = rest.rsplit(":", 1)
            exp = int(exp_s)
            meta = json.loads(v)
        except (ValueError, json.JSONDecodeError):
            continue
        is_rev = (obj_id, exp) in revoked
        if not include_dead and (is_rev or exp <= now):
            continue  # live view skips dead links entirely
        row = db.get_object(obj_id)
        rows.append({
            "obj_id": obj_id,
            "filename": (row["filename"] if row else None),
            "exists": row is not None,
            "exp": exp,
            "expired": exp <= now,
            "revoked": is_rev,
            **meta,
        })
    if include_dead:
        # tombstones whose registration was already purged still show
        known = {(r["obj_id"], r["exp"]) for r in rows}
        for (obj_id, exp) in revoked:
            if (obj_id, exp) not in known:
                row = db.get_object(obj_id)
                rows.append({"obj_id": obj_id,
                             "filename": (row["filename"] if row else None),
                             "exists": row is not None, "exp": exp,
                             "expired": exp <= now, "revoked": True,
                             "slug": None, "pw": False, "max_dl": None})
    rows.sort(key=lambda r: r["exp"], reverse=True)
    return rows[: max(1, limit)]


def purge_expired(db, now: int | None = None) -> int:
    """Drop expired registrations + stale tombstones. Returns removed count."""
    now = now or int(time.time())
    removed = 0
    for k, _v in list(db.kv_all()):
        if k.startswith(REV_PREFIX):
            # tombstones expire 7 days after their link would have
            try:
                _, obj_id, exp_s = k.split(":", 2)
                if int(exp_s) + 7 * 86400 < now:
                    db.kv_delete(k)
                    removed += 1
            except ValueError:
                continue
        elif k.startswith(KV_PREFIX):
            try:
                _, obj_id, exp_s = k.split(":", 2)
                if int(exp_s) <= now:
                    db.kv_delete(k)
                    removed += 1
                    _cleanup_tags(db, obj_id)
            except ValueError:
                continue
    return removed


def _cleanup_tags(db, obj_id: str) -> None:
    """When an object has no live links left, drop its pw/maxdl/slug tags."""
    for k, _ in db.kv_all():
        if k.startswith(KV_PREFIX) and k[len(KV_PREFIX):].startswith(obj_id + ":"):
            return  # another live link remains
    for tag in ("pw:", "maxdl:", "dlc:"):
        db.kv_delete(f"{tag}{obj_id}")
    for k, v in list(db.kv_all()):
        if k.startswith("slug:") and v == obj_id:
            db.kv_delete(k)
