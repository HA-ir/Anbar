"""Storage backend abstraction.

Backends store files in Telegram and expose an opaque `file_id`.
The object layer (F2/F3) sits above this and uses chunking transparently.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class ObjectRef:
    """Handle to stored bytes inside a backend.

    `message_id` is backend-specific extra context (bot: the channel message
    that holds the blob, needed to delete it). `size`/`name` are carried for
    convenience so the object layer can build manifests without re-reading.
    """

    file_id: str
    backend: str
    size: int = 0
    name: str = ""
    message_id: int | None = None


class StorageBackend(abc.ABC):
    """Pluggable storage: bot (F2) / mtproto (F5) / s3|local (future)."""

    name: str = "abstract"
    max_upload_bytes: int = 0

    @abc.abstractmethod
    async def store(
        self,
        data: bytes,
        name: str,
        content_type: str | None = None,
        caption: str | None = None,
    ) -> ObjectRef:
        """Store a single chunk/blob, return its ref."""

    @abc.abstractmethod
    async def open(self, ref: ObjectRef) -> bytes:
        """Fetch full blob. Object layer calls this per-chunk."""

    @abc.abstractmethod
    async def delete(self, ref: ObjectRef) -> bool:
        """Remove blob from remote. Returns True if it existed."""

    async def health(self) -> bool:
        return True

    async def send_text_event(self, text: str) -> dict | None:
        """Send a meta event text message to the storage channel (optional)."""
        return None

    async def connect(self) -> None:  # pragma: no cover - default no-op
        """Establish any backend connection (mtproto loads its session)."""
        return None

    async def close(self) -> None:  # pragma: no cover - default no-op
        return None


class FakeBackend(StorageBackend):
    """In-memory backend for tests — implements the exact same contract."""

    name = "fake"
    max_upload_bytes = 20 * 1024 * 1024

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}
        self.open_calls = 0
        self.store_calls = 0
        self._next_msg = 1

    async def store(
        self,
        data: bytes,
        name: str,
        content_type: str | None = None,
        caption: str | None = None,
    ) -> ObjectRef:
        self.store_calls += 1
        ref = f"fake-{len(self._store)}"
        self._store[ref] = bytes(data)
        msg = self._next_msg
        self._next_msg += 1
        return ObjectRef(
            file_id=ref,
            backend=self.name,
            size=len(data),
            name=name,
            message_id=msg,
        )

    async def open(self, ref: ObjectRef) -> bytes:
        self.open_calls += 1
        return self._store[ref.file_id]

    async def delete(self, ref: ObjectRef) -> bool:
        return self._store.pop(ref.file_id, None) is not None
