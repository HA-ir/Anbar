"""Download endpoints (F3/F4). Streaming, chunk-aware, Range-capable, signed.

The object layer hands out (chunk_index, offset, length) segments for a
byte range; we fetch each chunk from the backend on demand and stream the
requested slice. Memory stays bounded by one chunk, never the object.

Auth (F4):
  - auth OFF  → everything open (public mode)
  - auth ON   → download requires a bearer key (admin/uploader) OR a valid
                `?sig=...&exp=...` signed link (403 invalid, 410 expired)
  - DELETE    → owner (the bearer key that uploaded it) or admin
  - /f/{id}/link → mint a signed link (bearer key required)
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from .. import runtime
from ..auth import (
    effective_auth_enabled,
    effective_hmac_secret,
    sign,
    verify_sig,
    whoami,
)
from ..db import Database
from ..objects import Manifest
from ..ratelimit import limit_download
from ..storage import ObjectRef

router = APIRouter()

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-_]{0,63}")  # pretty link names
DEFAULT_LINK_TTL = 3600  # seconds
TTL_NEVER = 100 * 365 * 86400  # "never": ~100 years, signed but practically permanent


def _parse_range(header: str | None, total: int) -> tuple[int | None, int | None]:
    """Return (start, end) inclusive, or (None, None) for a full-range request."""
    if not header:
        return None, None
    m = _RANGE_RE.match(header.strip())
    if not m:
        raise _range_416(total)
    a, b = m.group(1), m.group(2)
    if not a and not b:
        raise _range_416(total)
    if not a:  # suffix range: last N bytes
        n = int(b)
        if n == 0:
            raise _range_416(total)
        return max(total - n, 0), total - 1
    start = int(a)
    end = int(b) if b else total - 1
    if start >= total or start > end:
        raise _range_416(total)
    return start, min(end, total - 1)


def _range_416(total: int) -> HTTPException:
    return HTTPException(416, "unsatisfiable range", headers={"Content-Range": f"bytes */{total}"})


def _password_page(obj_id: str, sig: str, exp: int, failed: bool = False) -> str:
    """Standalone RTL unlock page for a pw-protected link.

    The GET form keeps the link's `sig`/`exp` in hidden fields (a bare
    `?pw=` would drop them and fail auth), shows a server-driven error
    line when the previous try was wrong, and includes a show-password
    eye toggle.
    """
    html = """<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>anbar · قفل</title>
<style>
:root{--bg:#0b0f17;--bg2:#121826;--bg3:#1a2234;--line:#232c40;--line2:#2d3852;
--tx:#e7ecf5;--tx2:#aab3c5;--tx3:#6b7690;--brand:#2f6bff;--err:#ff5d6c}
@media(prefers-color-scheme:light){:root{--bg:#f3f6fb;--bg2:#ffffff;--bg3:#eaeff7;
--line:#dde3ee;--line2:#cbd3e4;--tx:#17202f;--tx2:#48536a;--tx3:#8590a8}}
*{box-sizing:border-box;margin:0}
body{font-family:'Vazirmatn',system-ui,-apple-system,'Segoe UI',Tahoma,sans-serif;
min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px;
background:radial-gradient(1200px 600px at 70% -10%,
rgba(47,107,255,.12),transparent 60%),var(--bg);color:var(--tx)}
.card{width:100%;max-width:380px;background:var(--bg2);border:1px solid var(--line);
border-radius:20px;padding:38px 30px;text-align:center;
box-shadow:0 18px 50px rgba(0,0,0,.25);animation:rise .35s cubic-bezier(.2,.9,.3,1.15)}
@keyframes rise{from{opacity:0;transform:translateY(14px) scale(.98)}to{opacity:1;transform:none}}
.lock{width:58px;height:58px;margin:0 auto 16px;border-radius:16px;display:flex;
align-items:center;justify-content:center;background:var(--bg3);color:var(--brand)}
h1{font-size:16.5px;font-weight:700;margin-bottom:6px}
p{font-size:12.5px;color:var(--tx2);margin-bottom:20px;line-height:1.9}
form{display:flex;gap:8px}
input{flex:1;min-width:0;padding:12px 14px;border:1.5px solid var(--line2);border-radius:12px;
background:var(--bg3);color:var(--tx);font-size:14px;font-family:inherit;outline:none;
transition:border .15s}
input:focus{border-color:var(--brand)}
button{padding:12px 18px;border:none;border-radius:12px;background:var(--brand);color:#fff;
font-family:inherit;font-size:13.5px;font-weight:700;cursor:pointer}
button:hover{filter:brightness(1.08)}
.err{display:none;color:var(--err);font-size:12px;margin-top:12px}
.foot{margin-top:22px;font-size:10.5px;color:var(--tx3);direction:ltr}
.pwrow{display:flex;gap:8px;align-items:stretch}
.pwwrap{position:relative;flex:1;min-width:0}
.pwwrap input{width:100%;padding-inline-end:44px}
.eye{position:absolute;inset-inline-end:6px;top:50%;transform:translateY(-50%);
background:none;border:none;padding:8px;color:var(--tx3);cursor:pointer;line-height:0}
.eye:hover{color:var(--tx)}
</style>
</head>
<body>
<div class="card">
  <div class="lock">
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18"
      height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
  </div>
  <h1>این فایل رمزدار است</h1>
  <p>برای دسترسی به فایل، رمز عبور لینک را وارد کنید.</p>
  <form method="get" action="" id="pf">
    <input type="hidden" name="sig" value="__SIG__">
    <input type="hidden" name="exp" value="__EXP__">
    <div class="pwrow">
      <div class="pwwrap">
        <input type="password" name="pw" id="pwin" autocomplete="off"
          autofocus placeholder="رمز عبور">
        <button type="button" class="eye" id="eyebtn" aria-label="نمایش رمز"
          title="نمایش رمز">
          <svg id="eye-open" width="18" height="18" viewBox="0 0 24 24"
            fill="none" stroke="currentColor" stroke-width="2"><path
            d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle
            cx="12" cy="12" r="3"/></svg>
          <svg id="eye-shut" width="18" height="18" viewBox="0 0 24 24"
            fill="none" stroke="currentColor" stroke-width="2" style="display:none"><path
            d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45
            18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11
            8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line
            x1="1" y1="1" x2="23" y2="23"/></svg>
        </button>
      </div>
      <button type="submit">باز کردن</button>
    </div>
  </form>
  <div class="err" id="perr">رمز عبور اشتباه است — دوباره تلاش کنید.</div>
  <div class="foot">powered by anbar</div>
</div>
<script>
var err=document.getElementById('perr');
__FAILED__
document.getElementById('pwin').focus();
document.getElementById('eyebtn').onclick=function(){
  var inp=document.getElementById('pwin'),o=document.getElementById('eye-open'),
      s=document.getElementById('eye-shut'),show=inp.type==='password';
  inp.type=show?'text':'password';
  o.style.display=show?'none':'';
  s.style.display=show?'':'none';
};
</script>
</body>
</html>"""
    html = (
        html.replace("__SIG__", sig)
        .replace("__EXP__", str(int(exp)))
        .replace("__FAILED__", "err.style.display='block';" if failed else "")
    )
    return html


def _authenticate_download(request: Request, obj_id: str) -> None:
    """Enforce the download auth matrix for this object (no-op when auth OFF)."""
    settings = request.app.state.settings
    db = request.app.state.db
    if not effective_auth_enabled(db, settings.auth_enabled):
        return
    role = whoami(request)
    if role in ("admin", "uploader"):
        return
    sig = request.query_params.get("sig")
    exp_raw = request.query_params.get("exp")
    if not sig or not exp_raw:
        raise HTTPException(401, "signed link or bearer key required")
    try:
        exp = int(exp_raw)
    except ValueError:
        raise HTTPException(403, "invalid signature") from None
    # revoked links die immediately even before expiry (v0.10)
    from .. import links as links_registry

    if links_registry.is_revoked(db, obj_id, exp):
        raise HTTPException(410, "link revoked")
    configured = settings.hmac_secret.get_secret_value() if settings.hmac_secret else None
    secret = effective_hmac_secret(db, configured)
    if not secret or not verify_sig(obj_id, exp, sig, secret):
        raise HTTPException(403, "invalid signature")
    if exp <= int(time.time()):
        raise HTTPException(410, "link expired")
    # optional per-object password (v0.9): kv holds an HMAC tag, the link
    # must carry ?pw=<plaintext> whose tag matches. Admin/uploader bypass.
    pw_tag = db.kv_get(f"pw:{obj_id}")
    if pw_tag:
        given = request.query_params.get("pw", "")
        configured2 = settings.hmac_secret.get_secret_value() if settings.hmac_secret else None
        secret2 = effective_hmac_secret(db, configured2) or ""
        want = hmac.new(
            secret2.encode(), f"pw:{obj_id}:{given}".encode(), hashlib.sha256
        ).hexdigest()[:32]
        if not hmac.compare_digest(want, pw_tag):
            raise HTTPException(
                403, "password required", headers={"WWW-Authenticate": 'xBasic realm="anbar-pw"'}
            )


@router.get("/{obj_id}")
async def download(request: Request, obj_id: str):
    settings = request.app.state.settings
    db = request.app.state.db
    backend = request.app.state.backend
    # pretty-link names (v0.9.5): /f/<slug> resolves to the real object id
    if not db.get_object(obj_id):
        resolved = db.kv_get(f"slug:{obj_id}")
        if resolved:
            obj_id = resolved
    # rate limit before auth: an anonymous hammerer gets 429, not endless 401s
    limit_download(
        db, request, obj_id, runtime.get_int(db, "rate_download", settings.rate_download_per_min)
    )
    row = db.get_object(obj_id)
    if row is None:
        raise HTTPException(404, "object not found")
    # v0.10.2: browser visit to a pw-protected link without the right ?pw
    # gets the unlock page. A carried valid sig/exp is reused in the form;
    # pretty-slug opens get a fresh 1h window (the pw tag only exists while
    # a live link does, so revoking the last link kills the page too).
    if (
        "text/html" in request.headers.get("accept", "")
        and effective_auth_enabled(db, settings.auth_enabled)
        and whoami(request) not in ("admin", "uploader")
    ):
        pw_tag = db.kv_get(f"pw:{obj_id}")
        if pw_tag:
            given = request.query_params.get("pw", "")
            configured0 = settings.hmac_secret.get_secret_value() if settings.hmac_secret else None
            # v0.10.3 fix: the tag is an HMAC (same as mint_link), not a
            # bare sha256 — the old precheck never matched, so even the
            # CORRECT password re-showed the "wrong password" page.
            secret0 = effective_hmac_secret(db, configured0) or ""
            want = hmac.new(
                secret0.encode(), f"pw:{obj_id}:{given}".encode(), hashlib.sha256
            ).hexdigest()[:32]
            if not hmac.compare_digest(want, pw_tag):
                configured = (
                    settings.hmac_secret.get_secret_value() if settings.hmac_secret else None
                )
                secret = effective_hmac_secret(db, configured)
                sig_q = request.query_params.get("sig")
                exp_q = request.query_params.get("exp")
                use_sig = use_exp = None
                if sig_q and exp_q and secret:
                    try:
                        exp_v = int(exp_q)
                        from .. import links as links_registry

                        if (
                            verify_sig(obj_id, exp_v, sig_q, secret)
                            and exp_v > int(time.time())
                            and not links_registry.is_revoked(db, obj_id, exp_v)
                        ):
                            use_sig, use_exp = sig_q, exp_v
                    except ValueError:
                        pass
                if use_sig is None and secret:
                    use_exp = int(time.time()) + 3600
                    use_sig = sign(obj_id, use_exp, secret)
                if use_sig:
                    return HTMLResponse(
                        _password_page(obj_id, use_sig, use_exp, failed=bool(given))
                    )
                # invalid/revoked/expired carried link → real error below
    _authenticate_download(request, obj_id)

    manifest = Manifest.from_json(row["manifest"])
    total = manifest.total_size
    start, end = _parse_range(request.headers.get("range"), total)
    if start is not None:
        assert end is not None
        length = end - start + 1
        segments = manifest.map_range(start, end + 1)  # [start, end) exclusive
    else:
        length = total
        segments = manifest.map_range(0, total)

    etag = f'"{row["sha256"]}"' if row["sha256"] else None
    if etag and start is None:
        if_none_match = request.headers.get("if-none-match")
        if if_none_match:
            tags = [t.strip() for t in if_none_match.split(",")]
            if "*" in tags or etag in tags or f"W/{etag}" in tags:
                return Response(status_code=304, headers={"ETag": etag, "Accept-Ranges": "bytes"})

    import mimetypes

    # Fallback to file extension guessing if content_type is generic octet-stream or missing
    resolved_ct = row["content_type"] or ""
    if not resolved_ct or resolved_ct == "application/octet-stream":
        guessed, _ = mimetypes.guess_type(row["filename"] or "")
        if guessed:
            resolved_ct = guessed

    ct = (resolved_ct or "").lower()
    is_media = (
        ct.startswith(("image/", "video/", "audio/", "text/"))
        or ct == "application/pdf"
    )
    req_view = request.query_params.get("view") in ("1", "true")
    req_dl = request.query_params.get("dl") in ("1", "true") or request.query_params.get(
        "download"
    ) in ("1", "true")

    if req_dl:
        disposition = "attachment"
    elif req_view or is_media:
        disposition = "inline"
    else:
        disposition = "attachment"

    headers = {
        "Content-Length": str(length),
        "Content-Type": resolved_ct or "application/octet-stream",
        "Content-Disposition": f'{disposition}; filename="{row["filename"]}"',
        "Accept-Ranges": "bytes",
    }
    if etag:
        headers["ETag"] = etag
    if start is not None:
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"
    status = 206 if start is not None else 200
    db.bump_downloads(obj_id)
    if start is None:
        # v0.10.4: per-link download stats (best-effort, full downloads only)
        from .. import links as links_registry

        links_registry.bump_link_downloads(db, request, obj_id)
    # per-link download cap (v0.9.2): count full downloads only, then 410
    maxdl = db.kv_get(f"maxdl:{obj_id}")
    if maxdl and start is None:
        try:
            used = int(db.kv_get(f"dlc:{obj_id}") or "0") + 1
            db.kv_set(f"dlc:{obj_id}", str(used))
            if used > int(maxdl):
                raise HTTPException(410, "download limit reached for this link")
        except ValueError:
            pass

    cache = getattr(request.app.state, "cache", None)
    use_cache = (
        cache is not None
        and start is None  # full downloads only; ranges stay on the backend path
        and total > 0
        and total <= runtime.get_int(db, "cache_mb", settings.cache_max_mb) * 1024 * 1024
    )

    if use_cache and (path := cache.get(obj_id)) is not None:
        # cache hit: stream the temp file, zero backend calls
        async def cached_stream():
            with open(path, "rb") as f:
                while chunk := f.read(1024 * 1024):
                    yield chunk

        return StreamingResponse(cached_stream(), status_code=status, headers=headers)

    hybrid_on = bool(runtime.get_int(db, "hybrid_enabled", 1 if settings.hybrid_enabled else 0))
    bot_pool = getattr(request.app.state, "bot_pool", None)
    bot_client = getattr(request.app.state, "bot_client", None)
    bot_provider = bot_pool or bot_client
    bot_timeout_ms = runtime.get_int(
        db,
        "hybrid_bot_timeout_ms",
        int(getattr(settings, "hybrid_bot_timeout_s", 1.5) * 1000),
    )
    bot_timeout_s = max(0.2, bot_timeout_ms / 1000.0)

    async def _fetch_chunk_bytes(chunk_obj) -> bytes:
        # If hybrid mode is active and we have a bot_file_id and bot_provider, try Bot CDN first
        if hybrid_on and bot_provider is not None and chunk_obj.bot_file_id:
            try:
                # Fast failover: if Bot CDN is in a 120s queue, fallback to MTProto quickly
                bot_ref = ObjectRef(file_id=chunk_obj.bot_file_id, backend="bot")
                return await asyncio.wait_for(bot_provider.open(bot_ref), timeout=bot_timeout_s)
            except Exception:
                # Fallback to main backend (MTProto)
                pass
        ref = ObjectRef(
            file_id=chunk_obj.file_id,
            message_id=chunk_obj.message_id,
            backend=backend.name,
        )
        return await backend.open(ref)

    if use_cache:
        # cache miss: stream from the backend AND fill a temp file; commit to
        # the cache only if the stream completes (client abort drops the file).
        # Each chunk index appears in at most one segment (map_range walks
        # contiguously), so per-request memory is one chunk, never the object.
        async def filling_stream():
            tmp = cache.new_entry_path()
            size = 0
            try:
                with open(tmp, "wb") as out:
                    for idx, off, n in segments:
                        chunk = await _fetch_chunk_bytes(manifest.chunks[idx])
                        part = chunk[off : off + n]
                        out.write(part)
                        size += len(part)
                        yield part
                if size == total:
                    cache.add(obj_id, tmp, size)
            except BaseException:  # client abort (GeneratorExit) or backend error
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise

        return StreamingResponse(filling_stream(), status_code=status, headers=headers)

    async def stream():
        # one chunk in flight per request — never the whole object
        for idx, off, n in segments:
            chunk = await _fetch_chunk_bytes(manifest.chunks[idx])
            yield chunk[off : off + n]

    return StreamingResponse(stream(), status_code=status, headers=headers)


@router.post("/{obj_id}/link")
async def mint_link(
    request: Request, obj_id: str, ttl: int = DEFAULT_LINK_TTL, password: str = "", max_dl: int = 0
):
    """Mint a signed download link: `{base_url}/f/{id}?sig=...&exp=...`.

    `ttl` is the validity window in seconds (default 1 h, capped at 7 d;
    ttl=0 means "never" — signed for ~100 years). `slug` (optional) gives
    the link a pretty name: `{base}/f/<slug>` serves the same object.
    `password` (optional): the link then requires `?pw=<password>` too —
    stored as an HMAC tag, never in plaintext. `max_dl` > 0 caps the
    number of downloads; the counter lives in kv and hits return 410.
    Requires a bearer key.
    """
    settings = request.app.state.settings
    db = request.app.state.db
    row = db.get_object(obj_id)
    if row is None:
        raise HTTPException(404, "object not found")
    role = whoami(request)
    if effective_auth_enabled(db, settings.auth_enabled) and role == "anon":
        raise HTTPException(401, "authentication required")
    configured = settings.hmac_secret.get_secret_value() if settings.hmac_secret else None
    secret = effective_hmac_secret(db, configured)
    if not secret:
        raise HTTPException(500, "hmac secret not configured")
    ttl = max(60, min(ttl, 7 * 86400)) if ttl else TTL_NEVER  # ttl=0 → never

    # -- custom link name (slug) ------------------------------------------
    # `slug` maps a pretty path /f/<slug> to this object: kv holds
    # `slug:<name>` → obj_id. Names are unique, lowercase-safe.
    slug = (request.query_params.get("slug") or "").strip().strip("/")
    if slug:
        if not _SLUG_RE.fullmatch(slug):
            raise HTTPException(400, "invalid slug: use 1-64 chars of [a-z0-9-_] (no leading '-')")
        owner = db.kv_get(f"slug:{slug}")
        if owner and owner != obj_id:
            raise HTTPException(409, "link name already taken")
        db.kv_set(f"slug:{slug}", obj_id)

    exp = int(time.time()) + ttl
    sig = sign(obj_id, exp, secret)
    base = settings.base_url.rstrip("/")
    url = f"{base}/f/{obj_id}?sig={sig}&exp={exp}"
    out: dict = {"url": url, "expires_at": exp, "ttl_seconds": ttl}
    if slug:
        out["slug"] = slug
        out["pretty_url"] = f"{base}/f/{slug}"

    from .. import links as links_registry

    links_registry.register_link(
        db, obj_id, exp, slug=slug or None, password_protected=bool(password.strip()), max_dl=max_dl
    )
    if password.strip():
        pw_tag = hmac.new(
            secret.encode(), f"pw:{obj_id}:{password.strip()}".encode(), hashlib.sha256
        ).hexdigest()[:32]
        db.kv_set(f"pw:{obj_id}", pw_tag)
        out["password_protected"] = True
    if max_dl > 0:
        db.kv_set(f"maxdl:{obj_id}", str(max_dl))
        db.kv_set(f"dlc:{obj_id}", "0")
        out["max_downloads"] = max_dl
    return out


@router.get("/{obj_id}/qr")
async def qr(request: Request, obj_id: str):
    """SVG QR code of the signed share link (admin/uploader)."""
    from fastapi.responses import Response

    from ..qrcode import qr_svg

    settings = request.app.state.settings
    row = request.app.state.db.get_object(obj_id)
    if row is None:
        raise HTTPException(404, "object not found")
    role = whoami(request)
    if effective_auth_enabled(request.app.state.db, settings.auth_enabled) and role == "anon":
        raise HTTPException(401, "authentication required")
    configured = settings.hmac_secret.get_secret_value() if settings.hmac_secret else None
    secret = effective_hmac_secret(request.app.state.db, configured)
    if not secret:
        raise HTTPException(500, "hmac secret not configured")
    ttl = 7 * 86400
    exp = int(time.time()) + ttl
    sig = sign(obj_id, exp, secret)
    url = f"{settings.base_url.rstrip('/')}/f/{obj_id}?sig={sig}&exp={exp}"
    return Response(
        content=qr_svg(url), media_type="image/svg+xml", headers={"Cache-Control": "no-store"}
    )


@router.delete("/{obj_id}")
async def delete(request: Request, obj_id: str, purge: bool = False):
    """Trash an object (soft delete) — or destroy it with ?purge=true.

    Soft delete hides the object everywhere and schedules real deletion
    after 7 days; restore brings it back. `purge=true` deletes the
    Telegram blobs right now (old hard-delete behaviour).
    """
    settings = request.app.state.settings
    db = request.app.state.db
    backend = request.app.state.backend
    row = db.get_object(obj_id, include_trashed=True)
    if row is None:
        raise HTTPException(404, "object not found")
    role = whoami(request)
    if effective_auth_enabled(db, settings.auth_enabled) and role == "anon":
        raise HTTPException(401, "authentication required")
    is_owner = bool(row["uploader_key"]) and _key_matches(request, row["uploader_key"])
    if not (role == "admin" or (role == "uploader" and is_owner)):
        raise HTTPException(403, "admin or owner key required")

    if not purge:
        # v0.10: soft delete → object vanishes from listings/downloads but
        # stays restorable for 7 days; blobs stay in Telegram untouched.
        if db.soft_delete(obj_id):
            cache = getattr(request.app.state, "cache", None)
            if cache is not None:
                cache.remove(obj_id)
            return {"trashed": True, "id": obj_id, "restore_within_s": Database.TRASH_TTL_S}
        # already trashed → fall through to a real purge (idempotent UI)

    deleted_blobs = await _purge_object_blobs(backend, db, row)
    cache = getattr(request.app.state, "cache", None)
    if cache is not None:
        cache.remove(obj_id)
    return {"purged": True, "id": obj_id, "blobs_removed": deleted_blobs}


@router.patch("/{obj_id}")
async def rename(request: Request, obj_id: str):
    """Rename an object (metadata only; blobs untouched). Admin/owner only."""
    db = request.app.state.db
    settings = request.app.state.settings
    row = db.get_object(obj_id)
    if row is None:
        raise HTTPException(404, "object not found")
    role = whoami(request)
    if effective_auth_enabled(db, settings.auth_enabled) and role == "anon":
        raise HTTPException(401, "authentication required")
    is_owner = bool(row["uploader_key"]) and _key_matches(request, row["uploader_key"])
    if not (role == "admin" or (role == "uploader" and is_owner)):
        raise HTTPException(403, "admin or owner key required")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "expected JSON {filename}") from None
    name = ((body or {}).get("filename") or "").strip()
    if not name or len(name) > 200 or "/" in name or "\\" in name:
        raise HTTPException(400, "invalid filename")
    if not db.rename_object(obj_id, name):
        raise HTTPException(404, "object not found")
    return {"renamed": True, "id": obj_id, "filename": name}


def _key_matches(request: Request, uploader_key: str) -> bool:
    """Compare the caller's bearer key against the stored uploader key."""
    auth = request.headers.get("authorization", "")
    key = auth[7:] if auth.lower().startswith("bearer ") else None
    if not key:
        return False
    from ..auth import constant_time_equal

    return constant_time_equal(key, uploader_key)


async def _purge_object_blobs(backend, db, row: dict) -> int:
    """Hard-destroy one object row + its Telegram blobs. Returns blob count."""
    obj_id = row["id"]
    manifest = json.loads(row["manifest"]) if row["manifest"] else {"chunks": []}
    deleted = 0
    for c in manifest.get("chunks", []):
        try:
            ref = ObjectRef(
                file_id=c["f"],
                message_id=c.get("m"),
                backend=row["backend"],
            )
            if await backend.delete(ref):
                deleted += 1
        except Exception:  # noqa: BLE001 - best-effort remote cleanup
            pass
    db.delete_object(obj_id)
    # drop per-object kv tags (pw, cap, slugs, link registrations/tombstones)
    from ..links import KV_PREFIX as _LK
    from ..links import REV_PREFIX as _RV

    for k, v in list(db.kv_all()):
        if (v == obj_id and k.startswith("slug:")) or (
            k.startswith((_LK, _RV)) and len(k.split(":", 2)) == 3 and k.split(":", 2)[1] == obj_id
        ):
            db.kv_delete(k)
    for tag in ("pw:", "maxdl:", "dlc:"):
        db.kv_delete(f"{tag}{obj_id}")
    return deleted


@router.get("/{obj_id}/info")
async def info(request: Request, obj_id: str):
    db = request.app.state.db
    row = db.get_object(obj_id)
    if row is None:
        raise HTTPException(404, "object not found")
    manifest = json.loads(row["manifest"]) if row["manifest"] else {"chunks": []}
    return JSONResponse(
        {
            "id": row["id"],
            "filename": row["filename"],
            "size": row["size"],
            "sha256": row["sha256"],
            "content_type": row["content_type"],
            "chunks": len(manifest.get("chunks", [])),
            "created_at": row["created_at"],
            "downloaded": row["downloaded"],
        }
    )


# ── bulk ZIP download (v0.10) ─────────────────────────────────────────────────
@router.post("/zip")
async def zip_download(request: Request):
    """Stream several objects as one ZIP archive.

    POST /f/zip  body: {"ids": ["id1", "id2", ...]}
    The archive is generated on the fly (O(chunk) memory) and piped to the
    client — nothing is buffered on disk. Admin/session only.
    """
    settings = request.app.state.settings
    db = request.app.state.db
    role = whoami(request)
    if effective_auth_enabled(db, settings.auth_enabled) and role == "anon":
        raise HTTPException(401, "authentication required")
    if role != "admin":
        raise HTTPException(403, "admin only")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "json body required") from None
    ids = body.get("ids") if isinstance(body, dict) else None
    if not ids or not isinstance(ids, list):
        raise HTTPException(400, "ids[] required")
    ids = [str(i) for i in ids][:100]  # sane cap

    entries: list[tuple[str, str, dict]] = []
    total = 0
    from ..zipper import entry_name

    used_names: set[str] = set()
    for oid in ids:
        row = db.get_object(oid)
        if row is None:
            continue  # skip missing instead of failing the whole archive
        manifest = json.loads(row["manifest"]) if row["manifest"] else {"chunks": []}
        name = entry_name(row["filename"], oid)
        stem, dot, ext = name.rpartition(".")
        base = name
        n = 1
        while base in used_names:
            n += 1
            base = f"{stem}-{n}{dot}{ext}" if dot else f"{name}-{n}"
        used_names.add(base)
        entries.append((base, oid, manifest))
        total += row["size"]
    if not entries:
        raise HTTPException(404, "no valid objects")
    if total > 8 * 1024**3:
        raise HTTPException(413, "selection too large for one archive (>8 GB)")

    backend = request.app.state.backend

    async def fetch_chunk(obj_id: str, chunk_index: int, chunk_offset: int, length: int) -> bytes:
        row = db.get_object(obj_id)
        if row is None:
            return b"\0" * length  # vanished mid-zip: keep offsets intact
        manifest = json.loads(row["manifest"]) if row["manifest"] else {"chunks": []}
        chunks = manifest.get("chunks", [])
        if chunk_index >= len(chunks):
            return b"\0" * length
        c = chunks[chunk_index]
        ref = ObjectRef(file_id=c["f"], message_id=c.get("m"), backend=row["backend"])
        blob = await backend.open(ref)
        return blob[chunk_offset : chunk_offset + length]

    from ..zipper import stream_zip

    stamp = time.strftime("%Y%m%d-%H%M%S")
    return StreamingResponse(
        stream_zip(entries, fetch_chunk),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="anbar-{stamp}.zip"',
            "Accept-Ranges": "none",
        },
    )


# ── shared album (v0.10.4): one public link → gallery page of many files ─────
ALBUM_PREFIX = "album:"  # album:<token> -> {"ids": [...], "created_at": int}


def _album_token(n: int = 12) -> str:
    import secrets

    alphabet = "abcdefghijkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(n))


@router.post("/album")
async def album_create(request: Request):
    """Mint one share link for several objects.

    POST /f/album  body: {"ids": [...], "title"?: str}
    Returns {"url": "<base>/a/<token>", "token": ...} — the page at /a/<token>
    shows a gallery with per-file view/download links (no auth needed).
    """
    settings = request.app.state.settings
    db = request.app.state.db
    role = whoami(request)
    if effective_auth_enabled(db, settings.auth_enabled) and role == "anon":
        raise HTTPException(401, "authentication required")
    if role != "admin":
        raise HTTPException(403, "admin only")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "json body required") from None
    ids = body.get("ids") if isinstance(body, dict) else None
    if not ids or not isinstance(ids, list):
        raise HTTPException(400, "ids[] required")
    title = str(body.get("title") or "").strip()[:120]
    clean = []
    for oid in [str(i) for i in ids][:100]:
        row = db.get_object(str(oid))
        if row is not None:
            clean.append({"id": oid, "filename": row["filename"], "size": row["size"]})
    if not clean:
        raise HTTPException(404, "no valid objects")
    token = _album_token()
    db.kv_set(
        f"{ALBUM_PREFIX}{token}",
        json.dumps(
            {
                "ids": [c["id"] for c in clean],
                "title": title,
                "created_at": int(time.time()),
            },
            separators=(",", ":"),
        ),
    )
    base = settings.base_url.rstrip("/")
    return {"token": token, "count": len(clean), "url": f"{base}/f/a/{token}"}


@router.get("/a/{token}", include_in_schema=False)
async def album_page(request: Request, token: str):
    """Public gallery page for a shared album (no auth)."""
    db = request.app.state.db
    settings = request.app.state.settings
    raw = db.kv_get(f"{ALBUM_PREFIX}{token}")
    if not raw:
        return HTMLResponse(
            '<!DOCTYPE html><html lang="fa" dir="rtl"><head>'
            '<meta charset="utf-8"><title>anbar</title></head>'
            '<body style="font-family:sans-serif;text-align:center;'
            'padding-top:20vh;color:#889">این آلبوم موجود نیست یا حذف شده.'
            "</body></html>",
            status_code=404,
        )
    data = json.loads(raw)
    items = []
    for oid in data.get("ids", []):
        row = db.get_object(oid)
        if row is None:
            continue  # deleted after sharing — just hide it
        kind = None
        ext = (row["filename"] or "").rsplit(".", 1)[-1].lower()
        ct = row["content_type"] or ""
        if ct.startswith(("image/", "photo")) or ext in {
            "jpg",
            "jpeg",
            "png",
            "gif",
            "webp",
            "bmp",
            "svg",
            "avif",
        }:
            kind = "image"
        elif ct.startswith("video/") or ext in {"mp4", "webm", "mkv", "mov", "avi", "m4v"}:
            kind = "video"
        elif ct.startswith("audio/") or ext in {"mp3", "ogg", "wav", "flac", "m4a", "opus", "aac"}:
            kind = "audio"
        elif ext == "pdf":
            kind = "pdf"
        items.append(
            {
                "id": oid,
                "name": row["filename"],
                "kind": kind,
                "ct": ct or "application/octet-stream",
                "size": row["size"],
                "sig": sign(
                    oid,
                    int(data["created_at"]) + 86400 * 30,
                    effective_hmac_secret(
                        db,
                        settings.hmac_secret.get_secret_value() if settings.hmac_secret else None,
                    ),
                ),
                "exp": int(data["created_at"]) + 86400 * 30,
            }
        )
    title = data.get("title") or f"anbar · {len(items)} فایل"
    import html as _html

    payload = json.dumps(items).replace("</", "<\\/")
    return HTMLResponse(
        f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{_html.escape(title)}</title>
<style>
:root{{--bg:#0b0f17;--bg2:#121826;--bg3:#1a2234;--line:#232c40;--line2:#2d3852;
--tx:#e7ecf5;--tx2:#aab3c5;--tx3:#6b7690;--brand:#2f6bff}}
@media(prefers-color-scheme:light){{:root{{--bg:#f3f6fb;--bg2:#fff;--bg3:#eaeff7;
--line:#dde3ee;--line2:#cbd3e4;--tx:#17202f;--tx2:#48536a;--tx3:#8590a8}}}}
*{{box-sizing:border-box;margin:0}}
body{{background:var(--bg);color:var(--tx);
font-family:'Vazirmatn',system-ui,'Segoe UI',Tahoma,sans-serif;padding:24px 16px}}
h1{{font-size:17px;font-weight:700;text-align:center;margin-bottom:4px}}
.sub{{text-align:center;color:var(--tx3);font-size:12px;margin-bottom:22px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:14px;
max-width:1100px;margin:0 auto}}
.cell{{background:var(--bg2);border:1px solid var(--line);border-radius:14px;overflow:hidden}}
.thumb{{height:130px;background:var(--bg3);display:flex;align-items:center;
justify-content:center;overflow:hidden;cursor:pointer;position:relative}}
.thumb img,.thumb video{{width:100%;height:100%;object-fit:cover}}
.thumb .ico{{color:var(--tx3);font-weight:800;font-size:13px;letter-spacing:.1em;
display:flex;flex-direction:column;align-items:center;gap:6px}}
.thumb .ico svg{{width:32px;height:32px;fill:none;stroke:currentColor;
stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}}
.gplay{{position:absolute;bottom:6px;left:6px;background:rgba(0,0,0,.55);color:#fff;
font-size:11px;padding:2px 7px;border-radius:8px}}
.cname{{font-size:12px;padding:9px 10px 2px;white-space:nowrap;overflow:hidden;
text-overflow:ellipsis;direction:ltr;text-align:left}}
.csub{{font-size:11px;color:var(--tx3);padding:0 10px 10px;display:flex;
justify-content:space-between;align-items:center}}
.csub a{{color:var(--brand);text-decoration:none;font-weight:700}}
.csub a:hover{{text-decoration:underline}}
.lightbox{{display:none;position:fixed;inset:0;background:rgba(5,8,14,.92);
z-index:50;align-items:center;justify-content:center;padding:20px;flex-direction:column;gap:14px}}
.lightbox.on{{display:flex}}
.lightbox img,.lightbox video{{max-width:94vw;max-height:80vh;border-radius:12px}}
.lightbox iframe{{width:min(900px,94vw);height:min(720px,84vh);
border:none;border-radius:12px;background:#fff}}
.lbclose{{position:absolute;top:14px;left:16px;background:none;border:none;
color:#fff;font-size:26px;cursor:pointer;padding:8px}}
.lbdl{{padding:10px 22px;border-radius:11px;background:var(--brand);color:#fff;
border:none;font-family:inherit;font-size:13.5px;font-weight:700;cursor:pointer;
text-decoration:none}}
@media(max-width:480px){{.grid{{grid-template-columns:repeat(auto-fill,minmax(130px,1fr))}}.thumb{{height:104px}}}}
</style>
</head>
<body>
<h1>{_html.escape(title)}</h1>
<div class="sub">{len(items)} فایل · anbar</div>
<div class="grid" id="grid"></div>
<div class="lightbox" id="lb">
  <button class="lbclose" id="lbc">✕</button>
  <div id="lbcnt"></div>
  <a class="lbdl" id="lbdl" download>دانلود</a>
</div>
<script>
const ITEMS = JSON.parse(__PAYLOAD__);
const grid = document.getElementById('grid');
function fmt(n){{
  if(n>=1073741824)return (n/1073741824).toFixed(1)+' GB';
  if(n>=1048576)return (n/1048576).toFixed(1)+' MB';
  if(n>=1024)return (n/1024).toFixed(0)+' KB';
  return n+' B';
}}
const ICO={{
pdf:'<svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12'
   +'a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg><span>PDF</span>',
audio:'<svg viewBox="0 0 24 24"><path d="M9 18V5l12-2v13"/>'
     +'<circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>',
other:'<svg viewBox="0 0 24 24"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2'
     +'h12a2 2 0 0 0 2-2V9z"/><path d="M13 2v7h7"/></svg>'}};
ITEMS.forEach((it,i)=>{{
  const url='/f/'+it.id+'?sig='+it.sig+'&exp='+it.exp;
  let th;
  if(it.kind==='image')th='<img loading="lazy" src="'+url+'" alt="">';
  else if(it.kind==='video')th='<video src="'+url+'#t=1.5" preload="metadata" muted>'
    +'</video><span class="gplay">▶</span>';
  else th='<div class="ico">'+(ICO[it.kind]||ICO.other)+'</div>';
  const cell=document.createElement('div');
  cell.className='cell';
  cell.innerHTML='<div class="thumb" data-i="'+i+'">'+th+'</div>'
    +'<div class="cname">'+(it.name||'file')+'</div>'
    +'<div class="csub"><span>'+fmt(it.size)+'</span>'
    +(it.kind==='pdf'?'<a href="'+url+'" target="_blank">نمایش ↗</a>'
      :'<a href="'+url+'" download>دانلود ⬇</a>')+'</div>';
  grid.appendChild(cell);
}});
const lb=document.getElementById('lb'),cnt=document.getElementById('lbcnt'),
      bdl=document.getElementById('lbdl');
function openLb(i){{
  const it=ITEMS[i],url='/f/'+it.id+'?sig='+it.sig+'&exp='+it.exp;
  if(it.kind==='image')cnt.innerHTML='<img src="'+url+'" alt="">';
  else if(it.kind==='video')cnt.innerHTML='<video src="'+url
    +'" controls autoplay></video>';
  else if(it.kind==='audio')cnt.innerHTML='<audio src="'+url
    +'" controls autoplay style="width:min(500px,90vw)"></audio>';
  else if(it.kind==='pdf')cnt.innerHTML='<iframe src="'+url+'"></iframe>';
  else cnt.innerHTML='';
  bdl.href=url;bdl.download=it.name||'file';
  lb.classList.add('on');
}}
grid.addEventListener('click',e=>{{
  const t=e.target.closest('.thumb');if(!t)return;
  openLb(+t.dataset.i);
}});
document.getElementById('lbc').onclick=()=>{{
  lb.classList.remove('on');cnt.innerHTML='';}};
lb.addEventListener('click',e=>{{
  if(e.target===lb){{lb.classList.remove('on');cnt.innerHTML='';}}}});
document.addEventListener('keydown',e=>{{
  if(e.key==='Escape'){{lb.classList.remove('on');cnt.innerHTML='';}}}});
</script>
</body>
</html>""".replace("__PAYLOAD__", payload)
    )
