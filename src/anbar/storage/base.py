"""Storage backend abstraction.

Backends store files in Telegram and expose an opaque `file_id`.
The object layer (F2/F3) sits above this and uses chunking transparently.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class ObjectRef:
    """Handle to stored bytes inside a backend."""
    file_id: str
    backend: str


class StorageBackend(abc.ABC):
    """Pluggable storage: bot (F2) / mtproto (F5) / s3|local (future)."""

    name: str = "abstract"
    max_upload_bytes: int = 0

    @abc.abstractmethod
    async def store(self, data: bytes, name: str) -> ObjectRef:
        """Store a single chunk/blob, return its ref."""

    @abc.abstractmethod
    async def open(self, ref: ObjectRef) -> bytes:
        """Fetch full blob. Object layer calls this per-chunk."""

    @abc.abstractmethod
    async def delete(self, ref: ObjectRef) -> bool:
        """Remove blob from remote. Returns True if it existed."""

    async def health(self) -> bool:
        return True


class FakeBackend(StorageBackend):
    """In-memory backend for tests — implements the exact same contract."""

    name = "fake"
    max_upload_bytes = 20 * 1024 * 1024

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    async def store(self, data: bytes, name: str) -> ObjectRef:
        ref = f"fake-{len(self._store)}"
        self._store[ref] = bytes(data)
        return ObjectRef(file_id=ref, backend=self.name)

    async def open(self, ref: ObjectRef) -> bytes:
        return self._store[ref.file_id]

    async def delete(self, ref: ObjectRef) -> bool:
        return self._store.pop(ref.file_id, None) is not None