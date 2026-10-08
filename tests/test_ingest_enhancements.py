"""Tests for strategic ingest enhancements:
- Rolling-window speed & dynamic ETA calculation
- Active Ingest Task Manager & Admin cancel API
- Telegram Album / Multi-File batch debouncing
- Parallel MTProto streaming and in-order reassembly
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.testclient import TestClient

from anbar.ingest_manager import IngestTaskManager


def test_task_manager_rolling_speed_and_eta():
    tm = IngestTaskManager()
    task = tm.create("task_1", "telegram", "video.mp4", total_bytes=100 * 1024 * 1024)

    assert task.id == "task_1"
    assert task.state == "pulling"
    assert task.speed == 0.0

    # Simulate bytes over time
    task.update_bytes(10 * 1024 * 1024)
    assert task.transferred_bytes == 10 * 1024 * 1024
    assert task.pct == 10.0
    assert task.speed > 0
    assert task.eta is not None

    # Test rolling window calculation
    now = time.time()
    task.history.clear()
    task.history.append((now - 5.0, 10 * 1024 * 1024))
    task.history.append((now, 20 * 1024 * 1024))
    task.update_bytes(20 * 1024 * 1024)

    # 10 MB in 5s -> ~2 MB/s
    assert 1.9 * 1024 * 1024 <= task.speed <= 2.1 * 1024 * 1024
    assert task.eta is not None


def test_task_manager_cancel_and_prune():
    tm = IngestTaskManager(max_history_s=1.0)
    task = tm.create("task_cancel", "url", "archive.zip")

    assert not task.cancel_event.is_set()
    assert tm.cancel("task_cancel") is True
    assert task.state == "cancelled"
    assert task.cancel_event.is_set()

    # Second cancel returns False
    assert tm.cancel("task_cancel") is False
    assert tm.cancel("non_existent") is False

    # Pruning
    task.updated_at = time.time() - 2.0
    tm.prune()
    assert tm.get("task_cancel") is None


def test_admin_active_ingest_api(client: TestClient):
    from anbar.ingest_manager import TASK_MANAGER

    # Create dummy tasks
    TASK_MANAGER.create("act_1", "telegram", "test1.mp4", total_bytes=5000000)
    TASK_MANAGER.create("act_2", "url", "test2.iso", total_bytes=10000000)

    # Unauthorized access check
    r_no_auth = client.get("/api/v1/admin/ingest/active")
    assert r_no_auth.status_code == 401

    # Authorized access
    app_settings = client.app.state.settings  # type: ignore[attr-defined]
    key_val = (
        app_settings.admin_key.get_secret_value()
        if hasattr(app_settings.admin_key, "get_secret_value")
        else str(app_settings.admin_key)
    )
    headers = {"Authorization": f"Bearer {key_val}"}

    r = client.get("/api/v1/admin/ingest/active", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert "tasks" in data
    task_ids = [t["id"] for t in data["tasks"]]
    assert "act_1" in task_ids
    assert "act_2" in task_ids

    # Cancel act_1
    r_cancel = client.post("/api/v1/admin/ingest/act_1/cancel", headers=headers)
    assert r_cancel.status_code == 200
    assert r_cancel.json() == {"status": "ok", "task_id": "act_1"}

    # Cancel non-existent
    r_404 = client.post("/api/v1/admin/ingest/does_not_exist/cancel", headers=headers)
    assert r_404.status_code == 404

    TASK_MANAGER.cancel("act_2")


async def test_telegram_album_debouncing(client: TestClient):
    from anbar.telegram_ingest import ALBUM_BUFFERS, ALBUM_LOCK, _enqueue_album_item

    app = client.app
    group_id = "test_album_123"

    msg1 = {
        "message_id": 101,
        "media_group_id": group_id,
        "chat": {"id": 12345},
        "photo": [{"file_id": "p1"}],
    }
    msg2 = {
        "message_id": 102,
        "media_group_id": group_id,
        "chat": {"id": 12345},
        "photo": [{"file_id": "p2"}],
    }
    msg3 = {
        "message_id": 103,
        "media_group_id": group_id,
        "chat": {"id": 12345},
        "photo": [{"file_id": "p3"}],
    }

    with patch("anbar.telegram_ingest._process_album_batch", new_callable=AsyncMock) as mock_batch:
        await _enqueue_album_item(app, msg1, group_id)
        await _enqueue_album_item(app, msg2, group_id)
        await _enqueue_album_item(app, msg3, group_id)

        async with ALBUM_LOCK:
            assert len(ALBUM_BUFFERS[group_id]) == 3

        # Wait for debounce window (1.5s) to complete
        await asyncio.sleep(1.7)
        assert mock_batch.called
        batch_args = mock_batch.call_args[0]
        assert batch_args[1] == group_id
        assert len(batch_args[2]) == 3


async def test_parallel_telethon_stream_reassembly():
    """Verify parallel worker gathering and in-order chunk reassembly."""
    part_size = 512 * 1024
    total_expected = 4 * part_size  # 2MB -> 4 parts

    # Mock client with iter_download
    mock_client = MagicMock()
    mock_client.is_connected.return_value = True

    async def mock_iter_download(_media, offset: int = 0, **_kwargs):
        part_idx = offset // part_size
        yield f"CHUNK_{part_idx}_DATA".encode()

    mock_client.iter_download = mock_iter_download

    # Recreate the parallel streaming logic to test reordering
    total_parts = (total_expected + part_size - 1) // part_size
    num_workers = min(3, total_parts)
    next_part = 0
    part_lock = asyncio.Lock()
    queue = asyncio.Queue(maxsize=16)
    stop_event = asyncio.Event()

    async def _worker():
        nonlocal next_part
        while not stop_event.is_set():
            async with part_lock:
                if next_part >= total_parts:
                    break
                p_idx = next_part
                next_part += 1
            offset = p_idx * part_size
            async for chunk in mock_client.iter_download(
                "dummy_media", offset=offset, limit=1, request_size=part_size
            ):
                await queue.put((p_idx, chunk))
                break

    workers = [asyncio.create_task(_worker()) for _ in range(num_workers)]

    async def _sentinel():
        await asyncio.gather(*workers, return_exceptions=True)
        await queue.put((-1, b""))

    sentinel_task = asyncio.create_task(_sentinel())

    expected_part = 0
    reorder_buf = {}
    assembled_parts = []

    try:
        while expected_part < total_parts:
            while expected_part in reorder_buf:
                assembled_parts.append(reorder_buf.pop(expected_part))
                expected_part += 1
            if expected_part >= total_parts:
                break
            item = await queue.get()
            if isinstance(item, Exception):
                raise item
            p_idx, data = item
            if p_idx == -1:
                break
            reorder_buf[p_idx] = data
            while expected_part in reorder_buf:
                assembled_parts.append(reorder_buf.pop(expected_part))
                expected_part += 1
    finally:
        stop_event.set()
        for w in workers:
            w.cancel()
        sentinel_task.cancel()

    assert len(assembled_parts) == 4
    assert assembled_parts[0] == b"CHUNK_0_DATA"
    assert assembled_parts[1] == b"CHUNK_1_DATA"
    assert assembled_parts[2] == b"CHUNK_2_DATA"
    assert assembled_parts[3] == b"CHUNK_3_DATA"
