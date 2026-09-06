"""Background task tracking to prevent garbage collection mid-flight (REL-C2)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine

log = logging.getLogger("anbar.tasks")

_BACKGROUND_TASKS: set[asyncio.Task] = set()


def spawn_background_task(coro: Coroutine, name: str | None = None) -> asyncio.Task:
    """Spawn an asyncio task and retain a strong reference until completion.

    Prevents garbage collection mid-execution and logs unhandled exceptions.
    """
    task = asyncio.create_task(coro, name=name)
    _BACKGROUND_TASKS.add(task)

    def _done_cb(t: asyncio.Task) -> None:
        _BACKGROUND_TASKS.discard(t)
        if not t.cancelled():
            exc = t.exception()
            if exc is not None:
                log.exception("Background task %s failed with exception: %s", t.get_name(), exc)

    task.add_done_callback(_done_cb)
    return task
