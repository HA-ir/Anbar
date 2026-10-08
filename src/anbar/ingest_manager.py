"""Centralized in-memory task manager for active background ingest tasks (Telegram & URL)."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class IngestTask:
    id: str
    source: str  # "telegram" | "telegram_album" | "url"
    filename: str
    total_bytes: int | None = None
    transferred_bytes: int = 0
    speed: float = 0.0
    eta: float | None = None
    state: str = "pulling"  # "pulling" | "committing" | "done" | "error" | "cancelled"
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    error: str | None = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    history: deque[tuple[float, int]] = field(
        default_factory=lambda: deque(maxlen=60)
    )  # (time, bytes)

    def update_bytes(self, current_bytes: int, window_s: float = 10.0) -> None:
        now = time.time()
        self.transferred_bytes = current_bytes
        self.updated_at = now
        self.history.append((now, current_bytes))

        # Calculate rolling speed within the last `window_s` seconds
        while len(self.history) > 1 and now - self.history[0][0] > window_s:
            self.history.popleft()

        if len(self.history) >= 2:
            dt = self.history[-1][0] - self.history[0][0]
            db = self.history[-1][1] - self.history[0][1]
            if dt > 0.3 and db >= 0:
                self.speed = db / dt
            else:
                elapsed = now - self.started_at
                self.speed = current_bytes / max(0.5, elapsed)
        else:
            elapsed = now - self.started_at
            self.speed = current_bytes / max(0.5, elapsed)

        if self.total_bytes and self.total_bytes > 0:
            remaining = max(0, self.total_bytes - current_bytes)
            self.eta = remaining / self.speed if self.speed > 0 else None
        else:
            self.eta = None

    @property
    def pct(self) -> float | None:
        if self.total_bytes and self.total_bytes > 0:
            return round(self.transferred_bytes / self.total_bytes * 100, 1)
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "filename": self.filename,
            "total_bytes": self.total_bytes,
            "transferred_bytes": self.transferred_bytes,
            "pct": self.pct,
            "speed": round(self.speed, 2),
            "eta": round(self.eta, 1) if self.eta is not None else None,
            "state": self.state,
            "started_at": self.started_at,
            "elapsed": round(time.time() - self.started_at, 1),
            "error": self.error,
        }


class IngestTaskManager:
    """Singleton task repository for tracking and canceling background ingests."""

    def __init__(self, max_history_s: float = 3600.0) -> None:
        self._tasks: dict[str, IngestTask] = {}
        self._lock = asyncio.Lock()
        self.max_history_s = max_history_s

    def create(
        self,
        task_id: str,
        source: str,
        filename: str,
        total_bytes: int | None = None,
    ) -> IngestTask:
        self.prune()
        task = IngestTask(
            id=task_id,
            source=source,
            filename=filename,
            total_bytes=total_bytes,
        )
        self._tasks[task_id] = task
        return task

    def get(self, task_id: str) -> IngestTask | None:
        return self._tasks.get(task_id)

    def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.state in ("pulling", "committing"):
            task.state = "cancelled"
            task.cancel_event.set()
            task.updated_at = time.time()
            return True
        return False

    def list_active(self) -> list[dict[str, Any]]:
        self.prune()
        return [
            t.to_dict()
            for t in sorted(self._tasks.values(), key=lambda x: x.started_at, reverse=True)
            if t.state in ("pulling", "committing")
        ]

    def list_all(self, limit: int = 50) -> list[dict[str, Any]]:
        self.prune()
        sorted_tasks = sorted(self._tasks.values(), key=lambda x: x.started_at, reverse=True)
        return [t.to_dict() for t in sorted_tasks[:limit]]

    def prune(self) -> None:
        now = time.time()
        stale = [
            tid
            for tid, t in self._tasks.items()
            if t.state in ("done", "error", "cancelled") and now - t.updated_at > self.max_history_s
        ]
        for tid in stale:
            self._tasks.pop(tid, None)


# Global singleton instance
TASK_MANAGER = IngestTaskManager()
