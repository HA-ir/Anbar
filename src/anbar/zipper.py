"""Streaming ZIP (v0.10): correct offsets via byte-counting bridge.

zipfile computes central-directory offsets from ``fileobj.tell()``. Our
bridge counts forwarded bytes so offsets are exact; the worker thread hands
chunks to an asyncio queue that the consumer streams out.
"""
from __future__ import annotations

import asyncio
import threading
import zipfile
from collections.abc import AsyncIterator

_END = object()   # sentinel: archive complete


class _LoopBridge:
    """Sync write()/tell() -> async queue bridge (byte-counting)."""

    def __init__(self, sink: asyncio.Queue, q_loop: asyncio.AbstractEventLoop) -> None:
        self._sink = sink
        self._q_loop = q_loop
        self._pos = 0
        self.failed = False

    def write(self, data: bytes | bytearray | memoryview) -> int:
        view = bytes(data)
        self._pos += len(view)
        asyncio.run_coroutine_threadsafe(self._sink.put(view),
                                         self._q_loop).result(120)
        return len(view)

    def flush(self) -> None:
        pass

    def tell(self) -> int:
        return self._pos

    def seekable(self) -> bool:
        return False  # data descriptors mode; offsets come from tell()


async def stream_zip(entries: list[tuple[str, str, dict]],
                     fetch_chunk) -> AsyncIterator[bytes]:
    """Yield zip bytes for `entries` = [(arcname, obj_id, manifest_dict)].

    `fetch_chunk(obj_id, chunk_index, chunk_offset, length) -> bytes` pulls
    one segment from the storage backend.
    """
    q: asyncio.Queue = asyncio.Queue(maxsize=32)
    q_loop = asyncio.get_running_loop()
    work_loop = asyncio.new_event_loop()
    box: dict[str, bytes] = {}

    def _segments(manifest: dict):
        for c in manifest.get("chunks", []):
            yield c["i"], 0, c["s"]

    def work() -> None:
        try:
            asyncio.set_event_loop(work_loop)
            bridge = _LoopBridge(q, q_loop)
            with zipfile.ZipFile(bridge, "w", compression=zipfile.ZIP_STORED,
                                 allowZip64=True) as zf:
                for name, obj_id, manifest in entries:
                    info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                    info.external_attr = 0o644 << 16
                    # zip64 always: sizes are unknown ahead of streaming and
                    # force_zip64 keeps the local header honest (data desc).
                    with zf.open(info, "w", force_zip64=True) as dst:
                        for i, off, length in _segments(manifest):
                            data = work_loop.run_until_complete(
                                fetch_chunk(obj_id, i, off, length))
                            dst.write(data)
        except Exception as e:  # noqa: BLE001 - surfaced on the consumer side
            import traceback

            traceback.print_exc()
            box["error"] = str(e).encode() or b"zip failed"
        finally:
            work_loop.close()
            asyncio.run_coroutine_threadsafe(q.put(_END), q_loop).result(60)

    threading.Thread(target=work, daemon=True, name="anbar-zip").start()
    while True:
        item = await q.get()
        if item is _END:
            break
        yield item
    if "error" in box:
        raise RuntimeError(box["error"].decode())


def entry_name(filename: str, obj_id: str) -> str:
    """Collision-free arcname: keep the filename, suffix the short id."""
    safe = (filename or "file").replace("\\", "_").replace("/", "_")
    while len(safe.encode()) > 120:
        stem, _, ext = safe.rpartition(".")
        if not stem:
            safe = safe[:110]
            break
        safe = f"{stem[:-1]}.{ext}" if len(stem) > 1 else safe[:110]
    return f"{safe}.{obj_id[-4:]}"
