"""Media-aware store: video → sendVideo, audio → sendAudio, else sendDocument."""
from __future__ import annotations

import pytest

from anbar.storage.bot_backend import BotBackend


class RecordingBackend(BotBackend):
    """Captures (method, fields, files) instead of hitting Telegram."""

    def __init__(self):
        super().__init__(bot_token="t", channel_id="c")
        self.calls = []

    async def _call_multipart(self, method, fields, files):
        self.calls.append((method, dict(fields), dict(files)))
        return {"message_id": 1, "document": {"file_id": "fid"}} if method == "sendDocument" \
            else {"message_id": 2, method[4:].lower(): {"file_id": "fid"}}


@pytest.fixture
def be():
    b = RecordingBackend()
    b.send_gap_s = 0
    return b


@pytest.mark.asyncio
async def test_video_goes_via_sendvideo(be):
    await be.store(b"x" * 10, "clip.mp4.part", content_type="video/mp4")
    assert be.calls[0][0] == "sendVideo"
    assert "video" in be.calls[0][2]
    assert be.calls[0][1].get("supports_streaming") == "true"


@pytest.mark.asyncio
async def test_audio_by_extension(be):
    await be.store(b"x" * 10, "song.mp3.part")
    assert be.calls[0][0] == "sendAudio"
    assert "audio" in be.calls[0][2]


@pytest.mark.asyncio
async def test_plain_stays_document(be):
    await be.store(b"x" * 10, "blob.bin.part", content_type="application/octet-stream")
    assert be.calls[0][0] == "sendDocument"
    assert "supports_streaming" not in be.calls[0][1]


@pytest.mark.asyncio
async def test_no_content_type_stays_document(be):
    """No content_type + non-media name → plain document."""
    await be.store(b"x" * 10, "archive.dat.part", content_type=None)
    assert be.calls[0][0] == "sendDocument"
