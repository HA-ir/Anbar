"""Admin endpoints (F4): status, auth toggle, secret rotation, object listing.

F8 adds runtime settings (rate limits, size ceiling, session TTL, cache
budget) and a cache purge.
"""
from __future__ import annotations

import json
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .. import runtime
from ..auth import (
    KV_AUTH,
    KV_HMAC_SECRET,
    add_api_key,
    effective_auth_enabled,
    list_api_keys,
    new_secret,
    require_admin,
    revoke_api_key,
)
from ..cache import DiskLRU

router = APIRouter()


def _env_defaults(s) -> dict[str, int]:
    return {
        "rate_download": s.rate_download_per_min,
        "rate_upload": s.rate_upload_per_min,
        "rate_login": s.rate_login_per_min,
        "max_upload_mb": s.max_upload_mb,
        "web_session_ttl": s.web_session_ttl,
        "cache_mb": s.cache_max_mb,
    }


@router.get("/admin/status")
async def status(request: Request):
    s = request.app.state.settings
    db = request.app.state.db
    backend = request.app.state.backend
    cache = getattr(request.app.state, "cache", None)
    cache_mb = runtime.get_int(db, "cache_mb", s.cache_max_mb)
    return {
        "status": "ok",
        "backend": getattr(backend, "name", s.backend.value),
        "auth_enabled": effective_auth_enabled(db, s.auth_enabled),
        "objects": len(db.list_objects(limit=1000)),
        "cache": (
            {"enabled": False} if cache is None
            else {"enabled": True, "entries": cache.count(),
                  "bytes": cache.size(),
                  "max_bytes": cache_mb * 1024 * 1024}
        ),
        # master switch from .env — UI shows "disabled" when false
        "cache_master": s.cache_enabled,
        "max_upload_bytes": runtime.get_int(db, "max_upload_mb", s.max_upload_mb)
        * 1024 * 1024,
        "settings": runtime.effective(db, _env_defaults(s)),
        "time": int(time.time()),
    }


@router.get("/admin/settings")
async def settings_get(request: Request):
    """Effective settings + env defaults + override flags. Admin key required."""
    require_admin(request)
    db = request.app.state.db
    s = request.app.state.settings
    return {"settings": runtime.effective(db, _env_defaults(s))}


@router.post("/admin/settings")
async def settings_update(request: Request):
    """Update any subset of the runtime settings. Admin key required.

    Body: ``{"rate_download": 50, "cache_mb": 0, ...}`` — unknown keys or
    out-of-range values → 422.
    """
    require_admin(request)
    db = request.app.state.db
    s = request.app.state.settings
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "expected JSON object") from None
    if not isinstance(body, dict) or not body:
        raise HTTPException(400, "expected non-empty JSON object")
    changed = {}
    for name, value in body.items():
        if name not in runtime.SPEC:
            raise HTTPException(422, f"unknown setting: {name}")
        try:
            changed[name] = runtime.set_int(db, name, value)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
    if "cache_mb" in changed:
        _sync_cache(request.app, db)
    return {"changed": changed,
            "settings": runtime.effective(db, _env_defaults(s))}


def _sync_cache(app, db) -> None:
    """(Re)build or tear down the LRU cache instance.

    ``ANBAR_CACHE_ENABLED`` is the master switch: when it is off, the disk
    cache must stay off regardless of any ``cache_mb`` override, preserving
    the zero-retention default.
    """
    s = app.state.settings
    cache_mb = runtime.get_int(db, "cache_mb", s.cache_max_mb)
    old = getattr(app.state, "cache", None)
    if old is not None:
        old.close()
    app.state.cache = (
        DiskLRU(s.cache_dir, cache_mb * 1024 * 1024)
        if s.cache_enabled and cache_mb else None
    )


@router.post("/admin/settings/reset")
async def settings_reset(request: Request):
    """Drop overrides (back to .env defaults). Body: {"keys": [...]} or all."""
    require_admin(request)
    db = request.app.state.db
    s = request.app.state.settings
    try:
        body = await request.json()
    except Exception:
        body = {}
    keys = body.get("keys") if isinstance(body, dict) else None
    names = [k for k in (keys or list(runtime.SPEC))]
    unknown = [k for k in names if k not in runtime.SPEC]
    if unknown:
        raise HTTPException(422, f"unknown setting: {', '.join(unknown)}")
    reset = {k: runtime.reset(db, k) for k in names}
    if "cache_mb" in names:
        _sync_cache(request.app, db)
    return {"reset": reset,
            "settings": runtime.effective(db, _env_defaults(s))}


@router.post("/admin/cache/purge")
async def cache_purge(request: Request):
    """Evict all cached objects (scratch space only — nothing is lost)."""
    require_admin(request)
    db = request.app.state.db
    app = request.app
    old = getattr(app.state, "cache", None)
    purged = old.count() if old is not None else 0
    _sync_cache(app, db)  # rebuild empty, or tear down if disabled
    return {"purged": purged}


@router.post("/admin/auth/toggle")
async def auth_toggle(request: Request):
    """Flip the auth switch at runtime — no restart. Admin key required.

    When auth is OFF, all endpoints are open (public mode). When ON, the
    configured keys and signed URLs are enforced again.
    """
    require_admin(request)
    db = request.app.state.db
    s = request.app.state.settings
    current = effective_auth_enabled(db, s.auth_enabled)
    db.kv_set(KV_AUTH, "0" if current else "1")
    return JSONResponse({"auth_enabled": not current})


@router.post("/admin/auth/rotate-secret")
async def rotate_secret(request: Request):
    """Generate a fresh HMAC signing secret. Old signed links become invalid
    (410) immediately; callers must mint new links. Admin key required.
    """
    require_admin(request)
    db = request.app.state.db
    secret = new_secret()
    db.kv_set(KV_HMAC_SECRET, secret)
    return {"hmac_secret": secret, "note": "previously minted links are now invalid"}


@router.get("/admin/objects")
async def objects(request: Request, limit: int = 50, offset: int = 0):
    """List stored objects (newest first). Admin key required."""
    require_admin(request)
    db = request.app.state.db
    limit = max(1, min(limit, 500))
    rows = db.list_objects(limit=limit, offset=max(0, offset))
    return {"objects": rows, "count": len(rows)}


@router.get("/admin/export")
async def export_metadata(request: Request, format: str = "json"):
    """Export object metadata as JSON or CSV (admin; backup/inventory)."""
    import csv
    import io

    from fastapi.responses import Response

    require_admin(request)
    db = request.app.state.db
    rows = db.list_objects(limit=500)
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "filename", "size", "chunks", "downloads",
                    "created_at", "content_type", "sha256"])
        for r in rows:
            m = r.get("manifest") or ""
            chunks = m.count('"f"') if isinstance(m, str) else 0
            w.writerow([r["id"], r["filename"], r["size"], chunks,
                        r.get("downloaded", 0), r.get("created_at", ""),
                        r.get("content_type", ""), (r.get("sha256") or "")[:16]])
        return Response(
            content=buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="anbar-objects.csv"'},
        )
    out = [{"id": r["id"], "filename": r["filename"], "size": r["size"],
            "downloaded": r.get("downloaded", 0), "created_at": r.get("created_at"),
            "sha256": (r.get("sha256") or "")} for r in rows]
    return Response(
        content=json.dumps({"exported": len(out), "objects": out}, ensure_ascii=False, indent=1),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="anbar-objects.json"'},
    )


# ── API key management (v0.8.7) ──────────────────────────────────────────────
@router.get("/admin/api-keys")
async def api_keys_list(request: Request):
    require_admin(request)
    keys = list_api_keys(request.app.state.db)
    # never echo full keys after creation — only id/name/created_at
    return {"keys": [{k: v for k, v in k_.items() if k != "key"} for k_ in keys]}


@router.post("/admin/api-keys")
async def api_keys_create(request: Request):
    require_admin(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    name = (body or {}).get("name", "") if isinstance(body, dict) else ""
    entry = add_api_key(request.app.state.db, name or "")
    return {"id": entry["id"], "name": entry["name"], "key": entry["key"],
            "note": "copy this key now — it is not shown again"}


@router.delete("/admin/api-keys/{key_id}")
async def api_keys_revoke(request: Request, key_id: str):
    require_admin(request)
    ok = revoke_api_key(request.app.state.db, key_id)
    if not ok:
        raise HTTPException(404, "unknown key id")
    return {"revoked": key_id}


# ── Share-link management (v0.10) ────────────────────────────────────────────
@router.get("/admin/links")
async def links_list(request: Request, limit: int = 200):
    """All registered share links (newest first): expiry, slug, state."""
    require_admin(request)
    from ..links import list_links

    return {"links": list_links(request.app.state.db, limit=limit)}


@router.post("/admin/links/{obj_id}/revoke/{exp}")
async def link_revoke(request: Request, obj_id: str, exp: int):
    """Kill one link immediately (its URL starts returning 410)."""
    require_admin(request)
    from .. import links as links_registry

    ok = links_registry.revoke(request.app.state.db, obj_id, exp)
    if not ok:
        raise HTTPException(404, "unknown link")
    return {"revoked": True, "obj_id": obj_id, "exp": exp}


@router.get("/admin/objects/{obj_id}/link-info")
async def link_info(request: Request, obj_id: str):
    """Links of a single object (used by the file detail modal)."""
    require_admin(request)
    from ..links import list_links

    rows = [r for r in list_links(request.app.state.db, limit=500)
            if r["obj_id"] == obj_id]
    return {"links": rows}


# ── Trash (v0.10) ─────────────────────────────────────────────────────────────
@router.get("/admin/links/{obj_id}/manage")
async def link_manage_page(request: Request, obj_id: str, exp: int):
    """Standalone manager page for one share link (admin/session only).

    Shows the link's current settings and lets the owner re-mint with a new
    TTL / password / download cap — the previous window is revoked in the
    same flow, so there is exactly one live link per row afterwards.
    """
    require_admin(request)
    db = request.app.state.db
    from ..links import list_links

    row = next((x for x in list_links(db, limit=500)
                if x["obj_id"] == obj_id and x["exp"] == exp), None)
    if row is None:
        raise HTTPException(404, "link not found")

    import html as _html

    def esc(s: object) -> str:
        return _html.escape(str(s or ""), quote=True)

    fname = esc(row["filename"])
    pw_checked = "checked" if row["pw"] else ""
    slug_js = esc(row["slug"]) if row["slug"] else ""
    ttl_opts = [(3600, "۱ ساعت"), (86400, "۲۴ ساعت"), (604800, "۷ روز"),
                (6048000, "۷۰ روز"), (0, "هرگز (بدون انقضا)")]
    opts = "\n".join(
        f'<option value="{v}"{" selected" if v == 86400 else ""}>{lbl}</option>'
        for v, lbl in ttl_opts)
    maxdl = int(row["max_dl"] or 0)
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>anbar · مدیریت لینک</title>
<style>
:root{{--bg:#0b0f17;--bg2:#121826;--bg3:#1a2234;--line:#232c40;--line2:#2d3852;
--tx:#e7ecf5;--tx2:#aab3c5;--tx3:#6b7690;--brand:#2f6bff;--ok:#31c48d;--err:#ff5d6c}}
@media(prefers-color-scheme:light){{:root{{--bg:#f3f6fb;--bg2:#ffffff;--bg3:#eaeff7;
--line:#dde3ee;--line2:#cbd3e4;--tx:#17202f;--tx2:#48536a;--tx3:#8590a8}}}}
*{{box-sizing:border-box;margin:0}}
body{{font-family:'Vazirmatn',system-ui,'Segoe UI',Tahoma,sans-serif;min-height:100vh;
display:flex;align-items:center;justify-content:center;padding:16px;color:var(--tx);
background:radial-gradient(1200px 600px at 70% -10%,
rgba(47,107,255,.12),transparent 60%),var(--bg)}}
.card{{width:100%;max-width:430px;background:var(--bg2);border:1px solid var(--line);
border-radius:18px;padding:26px 22px;box-shadow:0 18px 50px rgba(0,0,0,.25)}}
h1{{font-size:16px;font-weight:700;margin-bottom:4px}}
.fname{{font-size:12px;color:var(--tx3);margin-bottom:18px;direction:ltr;text-align:left}}
.row{{margin-bottom:14px}}
label{{display:block;font-size:12.5px;font-weight:600;margin-bottom:6px}}
input[type=text],input[type=number],select{{width:100%;padding:10px 12px;
border:1.5px solid var(--line2);border-radius:10px;background:var(--bg3);
color:var(--tx);font-family:inherit;font-size:13.5px;outline:none}}
input:focus,select:focus{{border-color:var(--brand)}}
.check{{display:flex;align-items:center;gap:7px;font-size:13px;cursor:pointer;user-select:none}}
.check input{{width:16px;height:16px;accent-color:var(--brand)}}
.actions{{display:flex;gap:8px;margin-top:20px}}
button{{flex:1;padding:11px 14px;border:none;border-radius:11px;font-family:inherit;
font-size:13.5px;font-weight:700;cursor:pointer}}
.primary{{background:var(--brand);color:#fff}}
.danger{{background:transparent;border:1.5px solid var(--err);color:var(--err);flex:0 0 auto;
padding-inline:18px}}
.msg{{display:none;margin-top:14px;padding:10px 12px;border-radius:10px;
font-size:12.5px;line-height:1.9}}
.msg.ok{{background:rgba(49,196,141,.12);color:var(--ok);word-break:break-word}}
.msg.err{{background:rgba(255,93,108,.12);color:var(--err)}}
.linkout{{margin-top:14px;display:none;background:var(--bg3);border:1px solid var(--line);
border-radius:10px;padding:10px 12px;font-family:ui-monospace,monospace;
font-size:11.5px;direction:ltr;text-align:left;word-break:break-all;user-select:all}}
@media(max-width:480px){{.card{{padding:20px 14px}}.actions{{flex-direction:column}}
.danger{{flex:auto}}}}
</style>
</head>
<body>
<div class="card">
  <h1>مدیریت لینک اشتراک</h1>
  <div class="fname">{fname}</div>
  <form id="mf">
    <div class="row">
      <label for="ttl">انقضای لینک</label>
      <select id="ttl">{opts}</select>
    </div>
    <div class="row">
      <label class="check"><input type="checkbox" id="haspw" {pw_checked}>
        محافظت با رمز عبور</label>
    </div>
    <div class="row" id="pwrow" style="display:none">
      <label for="npw">رمز عبور جدید</label>
      <input type="text" id="npw" autocomplete="off" placeholder="رمز دلخواه">
    </div>
    <div class="row">
      <label for="maxdl">سقف تعداد دانلود (۰ = بی‌نهایت)</label>
      <input type="number" id="maxdl" min="0" value="{maxdl}">
    </div>
    <div class="actions">
      <button type="submit" class="primary">ذخیره و ساخت لینک جدید</button>
      <button type="button" class="danger" id="revBtn">ابطال لینک</button>
    </div>
  </form>
  <div class="msg ok" id="mok"></div>
  <div class="msg err" id="merr"></div>
  <div class="linkout" id="lout"></div>
</div>
<script>
const OID = {obj_id!r}, OLD_EXP = {exp};
const SLUG = {slug_js!r};
const H = {{'Content-Type': 'application/json'}};

function show(id, txt) {{
  const e = document.getElementById(id);
  e.textContent = txt; e.style.display = 'block';
}}
document.getElementById('haspw').onchange = e => {{
  document.getElementById('pwrow').style.display =
    e.target.checked ? 'block' : 'none';
}};
document.getElementById('mf').onsubmit = async ev => {{
  ev.preventDefault();
  const ttl = parseInt(document.getElementById('ttl').value, 10);
  const hasPw = document.getElementById('haspw').checked;
  const npw = document.getElementById('npw').value.trim();
  if (hasPw && !npw) {{
    show('merr', 'برای محافظت با رمز، یک رمز وارد کنید.');
    return;
  }}
  const maxdl = parseInt(document.getElementById('maxdl').value, 10) || 0;
  try {{
    // revoke the current window first (idempotent; 404 is fine)
    await fetch('/api/v1/admin/links/' + OID + '/revoke/' + OLD_EXP,
      {{method: 'POST', headers: H}});
    let q = 'ttl=' + ttl + (hasPw ? '&password=' + encodeURIComponent(npw) : '')
      + (maxdl ? '&max_dl=' + maxdl : '')
      + (SLUG ? '&slug=' + encodeURIComponent(SLUG) : '');
    const r = await fetch('/f/' + OID + '/link?' + q,
      {{method: 'POST', headers: H}});
    if (!r.ok) throw new Error((await r.json()).detail || r.status);
    const j = await r.json();
    document.getElementById('merr').style.display = 'none';
    show('mok', 'لینک جدید ساخته شد — لینک قبلی ابطال شد:');
    const lo = document.getElementById('lout');
    lo.textContent = j.pretty_url || j.url;
    lo.style.display = 'block';
  }} catch (e) {{ show('merr', e.message || String(e)); }}
}};
document.getElementById('revBtn').onclick = async () => {{
  if (!confirm('این لینک برای همیشه ابطال شود؟')) return;
  try {{
    await fetch('/api/v1/admin/links/' + OID + '/revoke/' + OLD_EXP,
      {{method: 'POST', headers: H}});
    document.getElementById('mok').style.display = 'none';
    document.getElementById('lout').style.display = 'none';
    show('merr', 'لینک ابطال شد — این صفحه دیگر کار نمی‌کند.');
  }} catch (e) {{ show('merr', e.message || String(e)); }}
}};
document.getElementById('pwrow').style.display =
  document.getElementById('haspw').checked ? 'block' : 'none';
</script>
</body>
</html>""")


@router.get("/admin/trash")
async def trash_list(request: Request):
    require_admin(request)
    db = request.app.state.db
    import time as _time

    now = int(_time.time())
    items = []
    for r in db.list_objects(limit=500, trash=True):
        deleted_at = r.get("deleted_at") or 0
        items.append({
            **{k: v for k, v in r.items() if k != "deleted_at"},
            "deleted_at": deleted_at,
            "purge_in_s": max(0, db.TRASH_TTL_S - (now - deleted_at)),
        })
    return {"items": items, "count": len(items)}


@router.post("/admin/trash/{obj_id}/restore")
async def trash_restore(request: Request, obj_id: str):
    require_admin(request)
    ok = request.app.state.db.restore_object(obj_id)
    if not ok:
        raise HTTPException(404, "not in trash")
    return {"restored": obj_id}


@router.delete("/admin/trash/{obj_id}")
async def trash_purge_one(request: Request, obj_id: str):
    """Permanently destroy one trashed object (blobs + metadata) now."""
    from ..api.download import _purge_object_blobs

    require_admin(request)
    db = request.app.state.db
    row = db.get_object(obj_id, include_trashed=True)
    if row is None:
        raise HTTPException(404, "object not found")
    removed = await _purge_object_blobs(request.app.state.backend, db, row)
    return {"purged": obj_id, "blobs_removed": removed}