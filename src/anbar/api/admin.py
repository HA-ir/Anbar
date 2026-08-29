"""Admin endpoints (F4): status, auth toggle, secret rotation, object listing.

F8 adds runtime settings (rate limits, size ceiling, session TTL, cache
budget) and a cache purge.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from .. import runtime
from ..auth import (
    KV_AUTH,
    KV_HMAC_SECRET,
    add_api_key,
    effective_auth_enabled,
    effective_hmac_secret,
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
        "mtproto_export_conns": getattr(s, "mtproto_export_conns", 0),
        "hybrid_enabled": 1 if getattr(s, "hybrid_enabled", False) else 0,
        "hybrid_bot_timeout_ms": int(getattr(s, "hybrid_bot_timeout_s", 1.5) * 1000),
        "encryption_enabled": 0,
        "auto_backup_enabled": 1 if getattr(s, "auto_backup_enabled", True) else 0,
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
            {"enabled": False}
            if cache is None
            else {
                "enabled": True,
                "entries": cache.count(),
                "bytes": cache.size(),
                "max_bytes": cache_mb * 1024 * 1024,
            }
        ),
        # master switch from .env — UI shows "disabled" when false
        "cache_master": s.cache_enabled,
        "max_upload_bytes": runtime.get_int(db, "max_upload_mb", s.max_upload_mb) * 1024 * 1024,
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
    if "mtproto_export_conns" in changed:
        backend = request.app.state.backend
        if hasattr(backend, "set_export_conns"):
            await backend.set_export_conns(changed["mtproto_export_conns"])
    db.log_audit("settings.update", actor="admin", details=changed)
    return {"changed": changed, "settings": runtime.effective(db, _env_defaults(s))}


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
        DiskLRU(s.cache_dir, cache_mb * 1024 * 1024) if s.cache_enabled and cache_mb else None
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
    return {"reset": reset, "settings": runtime.effective(db, _env_defaults(s))}


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
    db.log_audit("auth.toggle", actor="admin", details={"auth_enabled": not current})
    return JSONResponse({"auth_enabled": not current})


@router.get("/admin/auth/secret")
async def secret_get(request: Request):
    """Retrieve current HMAC / encryption secret (admin only)."""
    require_admin(request)
    db = request.app.state.db
    s = request.app.state.settings
    env_secret = s.hmac_secret.get_secret_value() if s.hmac_secret else None
    secret = effective_hmac_secret(db, env_secret)
    return {"secret": secret}


@router.post("/admin/auth/rotate-secret")
async def rotate_secret(request: Request):
    """Generate or set a fresh HMAC signing secret and encryption master key.
    Old signed links become invalid (410) immediately. Admin key required.
    """
    require_admin(request)
    db = request.app.state.db
    try:
        body = await request.json()
    except Exception:
        body = {}
    custom = body.get("secret", "").strip() if isinstance(body, dict) else ""
    if custom and len(custom) < 8:
        raise HTTPException(422, "Secret key must be at least 8 characters long")
    secret = custom or new_secret()
    db.kv_set(KV_HMAC_SECRET, secret)
    db.log_audit("secret.rotate", actor="admin", details={"custom": bool(custom)})
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
        w.writerow(
            [
                "id",
                "filename",
                "size",
                "chunks",
                "downloads",
                "created_at",
                "content_type",
                "sha256",
            ]
        )
        for r in rows:
            m = r.get("manifest") or ""
            chunks = m.count('"f"') if isinstance(m, str) else 0
            w.writerow(
                [
                    r["id"],
                    r["filename"],
                    r["size"],
                    chunks,
                    r.get("downloaded", 0),
                    r.get("created_at", ""),
                    r.get("content_type", ""),
                    (r.get("sha256") or "")[:16],
                ]
            )
        return Response(
            content=buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="anbar-objects.csv"'},
        )
    out = [
        {
            "id": r["id"],
            "filename": r["filename"],
            "size": r["size"],
            "downloaded": r.get("downloaded", 0),
            "created_at": r.get("created_at"),
            "sha256": (r.get("sha256") or ""),
        }
        for r in rows
    ]
    return Response(
        content=json.dumps({"exported": len(out), "objects": out}, ensure_ascii=False, indent=1),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="anbar-objects.json"'},
    )


@router.get("/admin/backup")
async def backup_download(request: Request):
    """Download consistent SQLite database binary backup (admin only)."""
    require_admin(request)
    db = request.app.state.db
    data = db.backup_bytes()
    ts = time.strftime("%Y%m%d_%H%M%S")
    filename = f"anbar_backup_{ts}.db"
    return Response(
        content=data,
        media_type="application/vnd.sqlite3",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/admin/backup/telegram")
async def backup_push_telegram(request: Request):
    """Push consistent SQLite database backup directly to Telegram storage channel."""
    require_admin(request)
    db = request.app.state.db
    backend = request.app.state.backend
    data = db.backup_bytes()
    ts = time.strftime("%Y%m%d_%H%M%S")
    name = f"backup_{ts}.db"
    ref = await backend.store(data, name)
    db.kv_set("last_backup_time", str(int(time.time())))
    db.kv_set("last_backup_ref", ref.file_id)
    db.log_audit("backup.telegram", actor="admin", target=name, details={"size": len(data)})
    return {
        "status": "ok",
        "backup_time": int(time.time()),
        "size": len(data),
        "file_id": ref.file_id,
        "message_id": ref.message_id,
    }


@router.post("/admin/backup/import")
async def backup_import(request: Request, file: UploadFile):
    """Import and restore a binary SQLite database backup file (admin only)."""
    require_admin(request)
    db = request.app.state.db
    content = await file.read()
    try:
        res = db.restore_bytes(content)
        db.log_audit("backup.restore", actor="admin", details=res)
        return {
            "status": "ok",
            "message": "Database restored successfully",
            **res,
        }
    except ValueError as e:
        raise HTTPException(400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(500, detail=f"Database restore failed: {e}") from e


@router.post("/admin/channel/rebuild")
async def channel_rebuild(request: Request):
    """Scan Telegram storage channel history and reconstruct SQLite objects.

    Self-healing disaster recovery: recovers filenames, folders, manifests and files
    even if the entire local database was deleted.
    """
    require_admin(request)
    db = request.app.state.db
    backend = request.app.state.backend
    s = request.app.state.settings
    try:
        body = await request.json()
    except Exception:
        body = {}
    limit = int((body or {}).get("limit", 1000)) if isinstance(body, dict) else 1000
    custom_secret = (body or {}).get("secret", "").strip() if isinstance(body, dict) else ""
    env_secret = s.hmac_secret.get_secret_value() if s.hmac_secret else None
    active_secret = custom_secret or effective_hmac_secret(db, env_secret)

    from ..self_healing import decode_chunk_caption, decode_meta_event, rebuild_from_manifests

    collected_chunks: dict[str, list[dict]] = {}
    collected_events: list[dict] = []

    if hasattr(backend, "_client") and hasattr(backend, "_peer") and hasattr(backend, "_connected"):
        try:
            if not backend._connected:
                await backend.connect()
            async for msg in backend._client.iter_messages(backend._peer, limit=limit):
                if not msg:
                    continue
                text = msg.text or msg.message or ""
                # 1. Check for journal meta event
                evt = decode_meta_event(text, secret=active_secret)
                if evt:
                    collected_events.append(evt)
                    continue

                # 2. Check for chunk document
                if not msg.media or not getattr(msg.media, "document", None):
                    continue
                caption = text or getattr(msg, "caption", "") or ""
                meta = decode_chunk_caption(caption, secret=active_secret)
                if not meta:
                    continue
                obj_id = str(meta.get("id") or meta.get("fn") or "unk")
                doc = msg.media.document
                collected_chunks.setdefault(obj_id, []).append(
                    {
                        "meta": meta,
                        "file_id": str(doc.id),
                        "message_id": msg.id,
                        "size": doc.size,
                        "backend": "mtproto",
                    }
                )
        except Exception as e:
            raise HTTPException(502, f"Failed scanning MTProto channel history: {e}") from e

    res = rebuild_from_manifests(collected_chunks, db, events=collected_events)
    db.log_audit("channel.rebuild", actor="admin", details=res)
    return {"status": "ok", **res}


@router.get("/admin/system-stats")
async def system_stats_get(request: Request):
    """Comprehensive telemetry and health stats for Admin Dashboard."""
    require_admin(request)
    db = request.app.state.db
    s = request.app.state.settings
    rows = db.list_objects(limit=1000)
    total_bytes = sum(r.get("size", 0) for r in rows)
    total_dl = sum(r.get("downloaded", 0) for r in rows)
    backend_str = s.backend.value if hasattr(s.backend, "value") else str(s.backend)
    tokens_count = len(getattr(s, "bot_tokens", []))
    last_backup_ts = db.kv_get("last_backup_time")
    enc_default = 1 if getattr(s, "encryption_enabled", True) else 0
    hyb_default = 1 if getattr(s, "hybrid_enabled", False) else 0
    encryption_on = bool(runtime.get_int(db, "encryption_enabled", enc_default))
    hybrid_on = bool(runtime.get_int(db, "hybrid_enabled", hyb_default))

    # File size category breakdown
    breakdown = {
        "image": 0,
        "video": 0,
        "audio": 0,
        "pdf": 0,
        "text": 0,
        "archive": 0,
        "other": 0,
    }
    img_exts = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif")
    vid_exts = (".mp4", ".webm", ".mkv", ".mov", ".avi")
    aud_exts = (".mp3", ".ogg", ".wav", ".flac", ".m4a", ".opus", ".aac")
    txt_exts = (
        ".txt", ".json", ".js", ".ts", ".py", ".md", ".sh",
        ".yaml", ".yml", ".html", ".css", ".sql",
    )
    arc_exts = (".zip", ".tar", ".gz", ".7z", ".rar", ".bz2", ".xz")

    for r in rows:
        sz = int(r.get("size") or 0)
        fn = (r.get("filename") or "").lower()
        ct = (r.get("content_type") or "").lower()
        if ct.startswith("image/") or fn.endswith(img_exts):
            breakdown["image"] += sz
        elif ct.startswith("video/") or fn.endswith(vid_exts):
            breakdown["video"] += sz
        elif ct.startswith("audio/") or fn.endswith(aud_exts):
            breakdown["audio"] += sz
        elif ct == "application/pdf" or fn.endswith(".pdf"):
            breakdown["pdf"] += sz
        elif ct.startswith("text/") or fn.endswith(txt_exts):
            breakdown["text"] += sz
        elif fn.endswith(arc_exts):
            breakdown["archive"] += sz
        else:
            breakdown["other"] += sz

    return {
        "status": "healthy",
        "version": getattr(request.app, "version", "0.14.3"),
        "backend": "hybrid" if (backend_str == "mtproto" and hybrid_on) else backend_str,
        "total_objects": len(rows),
        "total_bytes": total_bytes,
        "total_downloads": total_dl,
        "bot_tokens_count": tokens_count,
        "encryption_enabled": encryption_on,
        "hybrid_enabled": hybrid_on,
        "breakdown": breakdown,
        "last_backup_time": int(last_backup_ts) if last_backup_ts else None,
    }


@router.get("/admin/audit-logs")
async def audit_logs_list(request: Request, limit: int = 50, offset: int = 0):
    """List security and administrative audit logs."""
    require_admin(request)
    db = request.app.state.db
    logs = db.list_audit_logs(limit=limit, offset=offset)
    return {"logs": logs, "count": len(logs)}


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
    return {
        "id": entry["id"],
        "name": entry["name"],
        "key": entry["key"],
        "note": "copy this key now — it is not shown again",
    }


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


# ── Telegram & MTProto Env Config (v0.14.1) ──────────────────────────────────
def _mask_secret(val: str | None, visible: int = 4) -> str:
    if not val:
        return ""
    val = val.strip()
    if len(val) <= visible * 2:
        return "****"
    return val[:visible] + "•" * (len(val) - visible * 2) + val[-visible:]


def _get_env_file_path() -> Path:
    prod_env = Path("/opt/anbar/.env")
    if prod_env.exists():
        return prod_env
    local_env = Path(".env")
    return local_env


def _read_env_dict(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    res = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        res[k.strip()] = v.strip().strip("'\"")
    return res


def _write_env_dict(path: Path, updates: dict[str, str]) -> bool:
    try:
        if not path.exists():
            lines = []
        else:
            lines = path.read_text(encoding="utf-8").splitlines()

        seen = set()
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k = stripped.split("=", 1)[0].strip()
                if k in updates:
                    new_lines.append(f"{k}={updates[k]}")
                    seen.add(k)
                    continue
            new_lines.append(line)

        for k, v in updates.items():
            if k not in seen and v is not None:
                new_lines.append(f"{k}={v}")

        path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return True
    except OSError as exc:
        import logging

        logging.getLogger("anbar.admin").warning("Could not write .env file (%s): %s", path, exc)
        return False


@router.get("/admin/telegram-config")
async def telegram_config_get(request: Request):
    """Retrieve current Telegram & MTProto configuration for admin UI."""
    require_admin(request)
    s = request.app.state.settings
    env_path = _get_env_file_path()
    env_vars = _read_env_dict(env_path)

    backend = env_vars.get("ANBAR_BACKEND", s.backend.value)
    bot_tokens_raw = env_vars.get("ANBAR_BOT_TOKENS") or s.bot_tokens_raw or (
        s.bot_token.get_secret_value() if s.bot_token else ""
    )
    tokens_list = [t.strip() for t in (bot_tokens_raw or "").split(",") if t.strip()]
    masked_tokens = [_mask_secret(t, 6) for t in tokens_list]

    api_hash_raw = env_vars.get("ANBAR_API_HASH") or s.api_hash
    api_id_raw = env_vars.get("ANBAR_API_ID") or (str(s.api_id) if s.api_id else "")
    channel_id = env_vars.get("ANBAR_CHANNEL_ID", s.channel_id)
    channel_thread_id = env_vars.get(
        "ANBAR_CHANNEL_THREAD_ID",
        str(s.channel_thread_id) if s.channel_thread_id else "",
    )
    mtproto_peer = env_vars.get("ANBAR_MTPROTO_PEER", s.mtproto_peer)
    chunk_size_mb = int(env_vars.get("ANBAR_CHUNK_SIZE_MB", s.chunk_size_mb))
    db = request.app.state.db
    hybrid_runtime = bool(
        runtime.get_int(db, "hybrid_enabled", 1 if s.hybrid_enabled else 0)
    )
    hybrid_env = env_vars.get("ANBAR_HYBRID_ENABLED", "").lower() in ("true", "1", "yes")
    hybrid_enabled = hybrid_runtime or hybrid_env

    return {
        "backend": backend,
        "hybrid_enabled": hybrid_enabled,
        "bot_tokens_raw": bot_tokens_raw,
        "bot_tokens_count": len(tokens_list),
        "bot_tokens_masked": masked_tokens,
        "channel_id": channel_id,
        "channel_thread_id": channel_thread_id,
        "api_id": api_id_raw,
        "api_hash": api_hash_raw,
        "api_hash_masked": _mask_secret(api_hash_raw, 4),
        "api_hash_set": bool(api_hash_raw),
        "mtproto_peer": mtproto_peer,
        "chunk_size_mb": chunk_size_mb,
    }


@router.post("/admin/telegram-config")
async def telegram_config_update(request: Request):
    """Update Telegram and MTProto credentials and write safely to persistent .env."""
    require_admin(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "expected JSON body") from None

    if not isinstance(body, dict):
        raise HTTPException(400, "expected JSON object")

    env_path = _get_env_file_path()
    updates = {}

    if "backend" in body:
        b = str(body["backend"]).strip().lower()
        if b == "hybrid":
            updates["ANBAR_BACKEND"] = "mtproto"
            updates["ANBAR_HYBRID_ENABLED"] = "true"
            runtime.set_int(request.app.state.db, "hybrid_enabled", 1)
        elif b in ("bot", "mtproto", "fake"):
            updates["ANBAR_BACKEND"] = b
            if b == "bot":
                updates["ANBAR_HYBRID_ENABLED"] = "false"
                runtime.set_int(request.app.state.db, "hybrid_enabled", 0)
        else:
            raise HTTPException(422, "invalid backend (must be hybrid, bot, or mtproto)")

    if "hybrid_enabled" in body:
        h_on = bool(body["hybrid_enabled"])
        updates["ANBAR_HYBRID_ENABLED"] = "true" if h_on else "false"
        runtime.set_int(request.app.state.db, "hybrid_enabled", 1 if h_on else 0)

    if "bot_tokens" in body:
        tokens_val = str(body["bot_tokens"]).strip()
        updates["ANBAR_BOT_TOKENS"] = tokens_val
        first_token = tokens_val.split(",")[0].strip() if tokens_val else ""
        if first_token:
            updates["ANBAR_BOT_TOKEN"] = first_token

    if "channel_id" in body:
        cid = str(body["channel_id"]).strip()
        updates["ANBAR_CHANNEL_ID"] = cid

    if "channel_thread_id" in body:
        tid = str(body["channel_thread_id"]).strip()
        updates["ANBAR_CHANNEL_THREAD_ID"] = tid

    if "api_id" in body:
        aid = str(body["api_id"]).strip()
        if aid and not aid.isdigit():
            raise HTTPException(422, "api_id must be a numeric integer")
        updates["ANBAR_API_ID"] = aid

    if "api_hash" in body:
        ahash = str(body["api_hash"]).strip()
        if ahash and "•" not in ahash and "*" not in ahash:
            updates["ANBAR_API_HASH"] = ahash

    if "mtproto_peer" in body:
        peer = str(body["mtproto_peer"]).strip()
        updates["ANBAR_MTPROTO_PEER"] = peer

    if "chunk_size_mb" in body:
        try:
            cs = int(body["chunk_size_mb"])
            if cs < 1 or cs > 49:
                raise HTTPException(422, "chunk_size_mb must be between 1 and 49")
            updates["ANBAR_CHUNK_SIZE_MB"] = str(cs)
        except ValueError:
            raise HTTPException(422, "chunk_size_mb must be integer") from None

    _write_env_dict(env_path, updates)
    return {"status": "ok", "updated_keys": list(updates.keys())}


@router.post("/admin/links/revoke-all")
async def links_revoke_all(request: Request):
    """Revoke all registered links immediately."""
    require_admin(request)
    from .. import links as links_registry

    count = links_registry.revoke_all(request.app.state.db)
    request.app.state.db.log_audit("link.revoke_all", actor="admin", details={"count": count})
    return {"revoked": True, "count": count}


@router.post("/admin/links/{obj_id}/revoke/{exp}")
async def link_revoke(request: Request, obj_id: str, exp: int):
    """Kill one link immediately (its URL starts returning 410)."""
    require_admin(request)
    from .. import links as links_registry

    ok = links_registry.revoke(request.app.state.db, obj_id, exp)
    if not ok:
        raise HTTPException(404, "unknown link")
    request.app.state.db.log_audit("link.revoke", actor="admin", target=obj_id)
    return {"revoked": True, "obj_id": obj_id, "exp": exp}


@router.get("/admin/objects/{obj_id}/link-info")
async def link_info(request: Request, obj_id: str):
    """Links of a single object (used by the file detail modal)."""
    require_admin(request)
    from ..links import list_links

    rows = [r for r in list_links(request.app.state.db, limit=500) if r["obj_id"] == obj_id]
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

    row = next(
        (x for x in list_links(db, limit=500) if x["obj_id"] == obj_id and x["exp"] == exp), None
    )
    if row is None:
        raise HTTPException(404, "link not found")

    import html as _html

    def esc(s: object) -> str:
        return _html.escape(str(s or ""), quote=True)

    fname = esc(row["filename"])
    pw_checked = "checked" if row["pw"] else ""
    slug_js = esc(row["slug"]) if row["slug"] else ""
    ttl_opts = [
        (3600, "۱ ساعت"),
        (86400, "۲۴ ساعت"),
        (604800, "۷ روز"),
        (6048000, "۷۰ روز"),
        (0, "هرگز (بدون انقضا)"),
    ]
    opts = "\n".join(
        f'<option value="{v}"{" selected" if v == 86400 else ""}>{lbl}</option>'
        for v, lbl in ttl_opts
    )
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
        items.append(
            {
                **{k: v for k, v in r.items() if k != "deleted_at"},
                "deleted_at": deleted_at,
                "purge_in_s": max(0, db.TRASH_TTL_S - (now - deleted_at)),
            }
        )
    return {"items": items, "count": len(items)}


@router.post("/admin/trash/{obj_id}/restore")
async def trash_restore(request: Request, obj_id: str):
    require_admin(request)
    ok = request.app.state.db.restore_object(obj_id)
    if not ok:
        raise HTTPException(404, "not in trash")
    return {"restored": obj_id}


@router.post("/admin/folders/create")
async def folder_create(request: Request):
    """Create an empty folder marker object (compatible with S3 virtual directory)."""
    require_admin(request)
    body = await request.json()
    folder_path = body.get("path", "").strip("/")
    if not folder_path:
        raise HTTPException(400, "folder path is required")
    folder_name = f"{folder_path}/"
    db = request.app.state.db
    # Check if folder or files inside already exist
    existing = db.list_objects_by_prefix(folder_name)
    if existing:
        return {"status": "exists", "folder": folder_name}

    import uuid
    dummy_manifest = json.dumps({"version": 1, "total_size": 0, "chunks": []})
    obj_id = uuid.uuid4().hex[:12]
    now = int(time.time())
    db.insert_object({
        "id": obj_id,
        "file_id": f"folder_{obj_id}",
        "backend": "virtual",
        "filename": folder_name,
        "size": 0,
        "content_type": "application/x-directory",
        "manifest": dummy_manifest,
        "created_at": now,
    })
    return {"status": "created", "folder": folder_name, "id": obj_id}


@router.post("/admin/folders/rename")
async def folder_rename(request: Request):
    """Rename or move a folder prefix."""
    require_admin(request)
    body = await request.json()
    old_path = body.get("old_path", "").strip("/")
    new_path = body.get("new_path", "").strip("/")
    if not old_path or not new_path:
        raise HTTPException(400, "both old_path and new_path are required")
    # moving a folder into itself (or one of its own subfolders) is illegal
    if new_path == old_path or new_path.startswith(old_path + "/"):
        raise HTTPException(400, "cannot move a folder into itself")
    db = request.app.state.db
    backend = request.app.state.backend
    s = request.app.state.settings
    moved_count = db.rename_folder(old_path, new_path)
    db.log_audit("folder.rename", actor="admin", target=f"{old_path} -> {new_path}")

    # Emit background event to Telegram channel
    from ..self_healing import emit_meta_event
    env_sec = s.hmac_secret.get_secret_value() if s.hmac_secret else None
    sec = effective_hmac_secret(db, env_sec)
    asyncio.create_task(
        emit_meta_event(backend, {"op": "rn_dir", "old": old_path, "new": new_path}, secret=sec)
    )

    return {"status": "renamed", "moved_count": moved_count, "new_path": new_path}


@router.post("/admin/folders/copy")
async def folder_copy(request: Request):
    """Duplicate all files from src_path to dst_path."""
    require_admin(request)
    body = await request.json()
    src_path = body.get("src_path", "").strip("/")
    dst_path = body.get("dst_path", "").strip("/")
    if not src_path or not dst_path:
        raise HTTPException(400, "both src_path and dst_path are required")
    db = request.app.state.db
    copied_count = db.copy_folder(src_path, dst_path)
    db.log_audit("folder.copy", actor="admin", target=f"{src_path} -> {dst_path}")
    return {"status": "copied", "copied_count": copied_count, "dst_path": dst_path}


@router.post("/admin/folders/delete")
async def folder_delete(request: Request):
    """Soft-delete all files inside a folder."""
    require_admin(request)
    body = await request.json()
    folder_path = body.get("path", "").strip("/")
    if not folder_path:
        raise HTTPException(400, "folder path is required")
    db = request.app.state.db
    deleted_count = db.soft_delete_folder(folder_path)
    db.log_audit("folder.delete", actor="admin", target=folder_path)
    return {"status": "deleted", "deleted_count": deleted_count, "folder": folder_path}


@router.post("/admin/objects/move")
async def objects_move(request: Request):
    """Move real objects into a folder (prefix). Basename preserved; existing
    names are never overwritten — collisions are reported as skipped.
    Folder *markers* are moved with /admin/folders/rename instead."""
    require_admin(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "expected JSON {ids, dest}") from None
    ids = body.get("ids") or []
    dest = (body.get("dest") or "").strip()
    if not isinstance(ids, list) or not ids:
        raise HTTPException(400, "ids must be a non-empty list")
    dest = dest.strip("/")
    if "/" not in dest and any(ch in dest for ch in '?%*|"<>\\'):
        raise HTTPException(400, "invalid destination path")
    db = request.app.state.db
    backend = request.app.state.backend
    s = request.app.state.settings
    res = db.move_objects_to_prefix([str(i) for i in ids], dest)
    db.log_audit("file.move", actor="admin", target=f"{len(ids)} items -> {dest}")

    # Emit background event to Telegram channel
    from ..self_healing import emit_meta_event
    env_sec = s.hmac_secret.get_secret_value() if s.hmac_secret else None
    sec = effective_hmac_secret(db, env_sec)
    asyncio.create_task(
        emit_meta_event(
            backend, {"op": "mv_obj", "ids": [str(i) for i in ids], "dest": dest}, secret=sec
        )
    )

    return {
        "status": "moved",
        "moved": res["moved"],
        "skipped": res["skipped"],
        "dest": dest + "/" if dest else "",
    }


@router.post("/admin/objects/copy")
async def object_copy(request: Request):
    """Duplicate an object's metadata pointing to the same storage chunks with a new ID."""
    require_admin(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "expected JSON {id, filename?}") from None
    obj_id = body.get("id")
    new_filename = body.get("filename")
    if not obj_id:
        raise HTTPException(400, "id is required")
    db = request.app.state.db
    res = db.copy_object(str(obj_id), new_filename)
    if not res:
        raise HTTPException(404, "object not found")
    db.log_audit("file.copy", actor="admin", target=str(obj_id))
    return {"status": "copied", "object": res}


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
    db.log_audit("file.purge", actor="admin", target=obj_id)

    # Emit background delete event
    from ..self_healing import emit_meta_event
    s = request.app.state.settings
    env_sec = s.hmac_secret.get_secret_value() if s.hmac_secret else None
    sec = effective_hmac_secret(db, env_sec)
    asyncio.create_task(
        emit_meta_event(request.app.state.backend, {"op": "del_obj", "id": obj_id}, secret=sec)
    )

    return {"purged": obj_id, "blobs_removed": removed}

