"""Telegram Bot Webhook endpoint (/api/v1/tg/webhook).

Receives incoming Telegram updates, authenticates the secret token header,
checks sender authorization, and immediately spawns the streaming ingestion pipeline.
"""

from __future__ import annotations

import hmac
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ..tasks import spawn_background_task
from ..telegram_ingest import execute_telegram_ingest

router = APIRouter(prefix="/tg")
log = logging.getLogger("anbar.tg_webhook")


@router.post("/webhook")
async def telegram_webhook(request: Request) -> dict[str, Any]:
    """Receive and process updates from Telegram Bot API."""
    settings = request.app.state.settings
    db = request.app.state.db

    # 1. Verify X-Telegram-Bot-Api-Secret-Token
    expected_secret = settings.effective_webhook_secret(db)
    received_secret = request.headers.get("x-telegram-bot-api-secret-token", "")

    if not hmac.compare_digest(received_secret, expected_secret):
        log.warning("Telegram webhook received with invalid secret token")
        raise HTTPException(status_code=403, detail="Invalid webhook secret token")

    # 2. Parse update payload
    try:
        update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from None

    # Feed update to bot_harvester if active (so channel posts map file_ids without polling)
    harvester = getattr(request.app.state, "harvester", None)
    if harvester is not None:
        try:
            harvester._process_update(update)
        except Exception as e:
            log.debug("harvester webhook feed notice: %s", e)

    message = update.get("message")
    if not message or not isinstance(message, dict):
        return {"ok": True, "status": "ignored"}

    sender = message.get("from", {})
    sender_id = sender.get("id")
    msg_id = message.get("message_id")

    # 3. Check sender authorization (Strict: ANBAR_OWNER_TG_IDS required; silent drop)
    allowed_ids = set(settings.owner_tg_ids)
    if db is not None and hasattr(db, "kv_get"):
        kv_oids = db.kv_get("cfg_tg_owner_ids")
        if kv_oids:
            for p in kv_oids.split(","):
                p_str = p.strip()
                if p_str.isdigit():
                    allowed_ids.add(int(p_str))

    # Never allow unauthorized users or empty configurations; silently drop without replying
    if not allowed_ids or not sender_id or sender_id not in allowed_ids:
        log.warning("Ignored Telegram ingest update from unauthorized sender %s", sender_id)
        return {"ok": True, "status": "unauthorized"}

    # 4. Dispatch streaming ingestion in background
    spawn_background_task(
        execute_telegram_ingest(request.app, message),
        name=f"tg_ingest:{msg_id or 'update'}",
    )

    return {"ok": True, "status": "enqueued"}
