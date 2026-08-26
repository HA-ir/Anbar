"""Unit tests for hybrid store and bot harvester."""
import asyncio
import pytest

from anbar.objects import Chunk, Manifest
from anbar.storage.base import FakeBackend, ObjectRef
from anbar.storage.bot_harvester import BotHarvester


def test_chunk_manifest_serialization_with_bot_file_id():
    m = Manifest(
        chunks=[
            Chunk(index=0, size=100, file_id="mt_fid_0", message_id=10, bot_file_id="bot_fid_0"),
            Chunk(index=1, size=200, file_id="mt_fid_1", message_id=11, bot_file_id=None),
        ],
        total_size=300,
    )
    raw = m.to_json()
    assert '"b":"bot_fid_0"' in raw
    assert '"b":' not in raw.split('"i":1')[1]

    loaded = Manifest.from_json(raw)
    assert len(loaded.chunks) == 2
    assert loaded.chunks[0].bot_file_id == "bot_fid_0"
    assert loaded.chunks[0].message_id == 10
    assert loaded.chunks[1].bot_file_id is None
    assert loaded.chunks[1].message_id == 11


@pytest.mark.asyncio
async def test_bot_harvester_event_resolution():
    harvester = BotHarvester("FAKE_TOKEN", "-100123456789")
    # simulate an incoming update via _process_update
    update = {
        "update_id": 42,
        "channel_post": {
            "message_id": 999,
            "chat": {"id": -100123456789},
            "document": {"file_id": "bot_harvested_abc123"},
        },
    }
    harvester._process_update(update)
    fid = await harvester.get_file_id_for_message(999, timeout=0.1)
    assert fid == "bot_harvested_abc123"
    await harvester.stop()
