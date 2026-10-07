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
from ..telegram_ingest import execute_telegram_ingest, send_telegram_message

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

    message = update.get("message")
    if not message or not isinstance(message, dict):
        return {"ok": True, "status": "ignored"}

    sender = message.get("from", {})
    sender_id = sender.get("id")
    chat_id = message.get("chat", {}).get("id")
    msg_id = message.get("message_id")

    # 3. Check sender authorization
    allowed_ids = settings.owner_tg_ids
    if allowed_ids and sender_id not in allowed_ids:
        log.warning("Unauthorized Telegram ingest attempt from user id %s", sender_id)
        bot_token = settings.bot_tokens[0] if settings.bot_tokens else None
        if bot_token and chat_id:
            await send_telegram_message(
                bot_token,
                chat_id,
                "⛔ <b>Access Denied:</b> Not authorized to ingest files into this Anbar instance.",
                reply_to_message_id=msg_id,
            )
        return {"ok": True, "status": "unauthorized"}

    # 4. Dispatch streaming ingestion in background
    spawn_background_task(
        execute_telegram_ingest(request.app, message),
        name=f"tg_ingest:{msg_id or 'update'}",
    )

    return {"ok": True, "status": "enqueued"}
