"""v0.11: test forum topic message_thread_id support."""

from __future__ import annotations

import pytest
from anbar.storage.bot_backend import BotBackend


@pytest.mark.asyncio
async def test_bot_backend_includes_thread_id():
    backend = BotBackend("dummy-token", "-1001234567890", channel_thread_id=42)
    assert backend._thread_id == 42

    backend_no_thread = BotBackend("dummy-token", "-1001234567890")
    assert backend_no_thread._thread_id is None
