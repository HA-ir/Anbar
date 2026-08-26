"""Post-ingest Telegram notification (v0.9).

When a URL ingest finishes, drop a short message into the storage channel
(the bot is already a member there) with the filename, size and public
link. Best-effort: notification failures never fail the ingest job.
"""

from __future__ import annotations

import logging

from ..storage.bot_backend import BotBackend

log = logging.getLogger("anbar.notify")


async def notify_ingest_done(
    backend, base_url: str, obj: dict, origin_url: str, elapsed_s: float
) -> None:
    """Best-effort channel ping after a successful URL pull."""
    if not isinstance(backend, BotBackend):
        return  # fake backend (tests) / mtproto has its own path later
    link = f"{base_url.rstrip('/')}{obj['url']}"
    text = (
        "📥 anbar ingest done\n"
        f"📄 {obj['filename']}\n"
        f"💾 {obj['size'] / 1048576:.1f} MB · {obj['chunks']} chunk · "
        f"{elapsed_s:.0f}s\n"
        f"🔗 {origin_url}\n"
        f"➡️ {link}"
    )
    try:
        await backend._call(
            "sendMessage", chat_id=backend._channel, text=text, disable_web_page_preview="true"
        )
    except Exception as e:  # noqa: BLE001 - notify must never break the job
        log.warning("ingest notification failed: %s", e)
