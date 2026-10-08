"""Tests for Telegram Bot Webhook endpoint and ingestion pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from starlette.testclient import TestClient

from anbar.config import Settings
from anbar.telegram_ingest import (
    format_eta,
    format_size,
    get_bot_storage_backend,
    parse_telegram_post_link,
    parse_web_url,
    render_progress_bar,
)


def test_format_size():
    assert format_size(0) == "0 B"
    assert format_size(500) == "500 B"
    assert format_size(1024) == "1.00 KB"
    assert format_size(1024 * 1024 * 5) == "5.00 MB"
    assert format_size(1024 * 1024 * 1024 * 2) == "2.00 GB"


def test_format_eta_and_progress_bar():
    assert format_eta(None) == "calculating..."
    assert format_eta(45) == "45s"
    assert format_eta(90) == "1m 30s"
    assert format_eta(3665) == "1h 01m"

    assert render_progress_bar(0) == "░░░░░░░░░░"
    assert render_progress_bar(50) == "█████░░░░░"
    assert render_progress_bar(100) == "██████████"


def test_parse_web_url():
    assert (
        parse_web_url("Download from https://example.com/archive.zip now")
        == "https://example.com/archive.zip"
    )
    assert parse_web_url("http://site.org/file.pdf") == "http://site.org/file.pdf"
    assert parse_web_url("https://t.me/c/123/45") is None
    assert parse_web_url("https://t.me/channel/45") is None
    assert parse_web_url("No URL here") is None


def test_parse_telegram_post_link():
    # Private channel / supergroup link
    priv = parse_telegram_post_link("Check this: https://t.me/c/123456789/42 please")
    assert priv == (-100123456789, 42)

    # Public channel / group link
    pub = parse_telegram_post_link("Source: https://t.me/super_channel/999")
    assert pub == ("super_channel", 999)

    # Ignored special URLs
    assert parse_telegram_post_link("https://t.me/joinchat/abcdef") is None
    assert parse_telegram_post_link("No link here") is None


def test_webhook_secret_validation(client: TestClient):
    app_settings: Settings = client.app.state.settings  # type: ignore[attr-defined]
    app_db = client.app.state.db  # type: ignore[attr-defined]
    secret = app_settings.effective_webhook_secret(app_db)

    # 1. Missing secret header -> 403
    r = client.post("/api/v1/tg/webhook", json={"update_id": 1})
    assert r.status_code == 403

    # 2. Invalid secret header -> 403
    r = client.post(
        "/api/v1/tg/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "invalid-secret"},
        json={"update_id": 1},
    )
    assert r.status_code == 403

    # 3. Valid secret header, non-message update -> 200 ignored
    r = client.post(
        "/api/v1/tg/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": secret},
        json={"update_id": 1},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "status": "ignored"}


def test_webhook_unauthorized_sender(client: TestClient):
    app_settings: Settings = client.app.state.settings  # type: ignore[attr-defined]
    app_db = client.app.state.db  # type: ignore[attr-defined]
    secret = app_settings.effective_webhook_secret(app_db)

    # Configure authorized owner ID and bot token
    app_settings.owner_tg_id = 999888777
    app_settings.bot_tokens_raw = "123456:TEST_TOKEN"

    # Send update from unauthorized sender 111222333
    payload = {
        "update_id": 100,
        "message": {
            "message_id": 10,
            "from": {"id": 111222333, "first_name": "Stranger"},
            "chat": {"id": 111222333},
            "text": "Hello bot",
        },
    }
    with patch("anbar.api.tg_webhook.send_telegram_message", new_callable=AsyncMock) as mock_send:
        r = client.post(
            "/api/v1/tg/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": secret},
            json=payload,
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True, "status": "unauthorized"}
        assert mock_send.called


def test_webhook_authorized_sender_enqueued(client: TestClient):
    app_settings: Settings = client.app.state.settings  # type: ignore[attr-defined]
    app_db = client.app.state.db  # type: ignore[attr-defined]
    secret = app_settings.effective_webhook_secret(app_db)

    app_settings.owner_tg_id = 999888777

    payload = {
        "update_id": 101,
        "message": {
            "message_id": 11,
            "from": {"id": 999888777, "first_name": "Owner"},
            "chat": {"id": 999888777},
            "document": {
                "file_id": "doc123",
                "file_name": "report.pdf",
                "mime_type": "application/pdf",
                "file_size": 2048,
            },
        },
    }

    with patch("anbar.api.tg_webhook.execute_telegram_ingest", new_callable=AsyncMock) as mock_ing:
        r = client.post(
            "/api/v1/tg/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": secret},
            json=payload,
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True, "status": "enqueued"}
        assert mock_ing.called


async def test_mode_a_direct_media_ingest(client: TestClient):
    from anbar.telegram_ingest import _ingest_direct_media

    app = client.app
    media_info = {
        "file_id": "fid_doc_test",
        "filename": "document.pdf",
        "size": 4096,
        "content_type": "application/pdf",
    }

    # Mock Bot API getFile response and download stream
    mock_get_file = MagicMock()
    mock_get_file.status_code = 200
    mock_get_file.json.return_value = {
        "ok": True,
        "result": {"file_id": "fid_doc_test", "file_path": "docs/document.pdf"},
    }

    mock_stream_resp = MagicMock()
    mock_stream_resp.status_code = 200

    async def _mock_bytes(_chunk_size):
        yield b"%PDF-1.4 test document content"

    mock_stream_resp.aiter_bytes = _mock_bytes

    class MockAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, *args, **kwargs):
            return mock_get_file

        def stream(self, *args, **kwargs):
            class _StreamContext:
                async def __aenter__(self):
                    return mock_stream_resp

                async def __aexit__(self, *args):
                    pass

            return _StreamContext()

    with (
        patch("httpx.AsyncClient", return_value=MockAsyncClient()),
        patch("anbar.telegram_ingest.edit_telegram_message", new_callable=AsyncMock) as mock_edit,
    ):
        await _ingest_direct_media(
            app=app,
            message={"message_id": 1, "chat": {"id": 12345}},
            media_info=media_info,
            bot_token="test_token",
            chat_id=12345,
            status_msg_id=77,
        )

        assert mock_edit.called
        call_text = mock_edit.call_args[0][3]
        assert "Saved to Anbar!" in call_text
        assert "document.pdf" in call_text


async def test_mode_b_protected_post_ingest(client: TestClient):
    from anbar.telegram_ingest import _ingest_protected_post

    app = client.app

    # Mock Telethon client & message
    mock_telethon = MagicMock()
    mock_msg = MagicMock()
    mock_msg.media = MagicMock()
    mock_msg.file = MagicMock()
    mock_msg.file.name = "restricted_video.mp4"
    mock_msg.file.mime_type = "video/mp4"
    mock_msg.file.size = 1048576

    mock_telethon.get_messages = AsyncMock(return_value=mock_msg)

    async def _mock_iter_download(*args, **kwargs):
        yield b"fake video chunk 1"
        yield b"fake video chunk 2"

    mock_telethon.iter_download = _mock_iter_download

    with (
        patch(
            "anbar.telegram_ingest.get_active_mtproto_client",
            new_callable=AsyncMock,
            return_value=mock_telethon,
        ),
        patch("anbar.telegram_ingest.edit_telegram_message", new_callable=AsyncMock) as mock_edit,
    ):
        await _ingest_protected_post(
            app=app,
            entity=-100123456789,
            target_msg_id=42,
            bot_token="test_token",
            chat_id=12345,
            status_msg_id=88,
        )

        assert mock_edit.called
        call_text = mock_edit.call_args[0][3]
        assert "Saved to Anbar!" in call_text
        assert "restricted_video.mp4" in call_text


def test_get_bot_storage_backend_selection(client: TestClient):
    app = client.app
    # Verify BotBackend or primary pool is selected to avoid MTProto upload ban
    backend, pool = get_bot_storage_backend(app)
    assert backend is not None


async def test_mode_c_web_url_ingest(client: TestClient):
    from anbar.telegram_ingest import _ingest_web_url

    app = client.app

    mock_stream_resp = MagicMock()
    mock_stream_resp.status_code = 200
    mock_stream_resp.url = "https://example.com/movie.mp4"
    mock_stream_resp.headers = {
        "content-disposition": 'attachment; filename="movie.mp4"',
        "content-type": "video/mp4",
        "content-length": "2048",
    }

    async def _mock_bytes(_chunk_size):
        yield b"fake movie stream bytes"

    mock_stream_resp.aiter_bytes = _mock_bytes

    class MockAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def stream(self, *args, **kwargs):
            class _StreamContext:
                async def __aenter__(self):
                    return mock_stream_resp

                async def __aexit__(self, *args):
                    pass

            return _StreamContext()

    with (
        patch("httpx.AsyncClient", return_value=MockAsyncClient()),
        patch("anbar.telegram_ingest.edit_telegram_message", new_callable=AsyncMock) as mock_edit,
    ):
        await _ingest_web_url(
            app=app,
            url="https://example.com/movie.mp4",
            bot_token="test_token",
            chat_id=12345,
            status_msg_id=99,
        )

        assert mock_edit.called
        call_text = mock_edit.call_args[0][3]
        assert "Saved to Anbar!" in call_text
        assert "movie.mp4" in call_text


async def test_mode_a_large_file_fallback_to_mtproto(client: TestClient):
    from anbar.telegram_ingest import _ingest_direct_media

    app = client.app
    message = {
        "message_id": 50,
        "chat": {"id": 12345},
        "document": {
            "file_id": "huge_file_id",
            "file_name": "large_archive.zip",
            "file_size": 50 * 1024 * 1024,
            "mime_type": "application/zip",
        },
    }
    media_info = {
        "file_id": "huge_file_id",
        "filename": "large_archive.zip",
        "size": 50 * 1024 * 1024,
        "content_type": "application/zip",
    }

    # Mock Telethon client & recent message
    mock_telethon = MagicMock()
    mock_msg = MagicMock()
    mock_msg.media = MagicMock()
    mock_telethon.get_messages = AsyncMock(return_value=[mock_msg])

    async def _mock_iter_download(*args, **kwargs):
        yield b"chunk 1"
        yield b"chunk 2"

    mock_telethon.iter_download = _mock_iter_download

    with (
        patch(
            "anbar.telegram_ingest.get_active_mtproto_client",
            new_callable=AsyncMock,
            return_value=mock_telethon,
        ),
        patch("anbar.telegram_ingest.edit_telegram_message", new_callable=AsyncMock) as mock_edit,
    ):
        await _ingest_direct_media(
            app=app,
            message=message,
            media_info=media_info,
            bot_token="123456:FAKE_TOKEN",
            chat_id=12345,
            status_msg_id=101,
        )

        assert mock_edit.called
        call_text = mock_edit.call_args[0][3]
        assert "Saved to Anbar!" in call_text
        assert "large_archive.zip" in call_text


async def test_bot_commands_help_status_stats(client: TestClient):
    from anbar.telegram_ingest import handle_bot_command

    app = client.app
    msg = {"message_id": 999}

    with patch("anbar.telegram_ingest.send_telegram_message", new_callable=AsyncMock) as mock_send:
        # 1. /help
        handled = await handle_bot_command(app, msg, "fake_token", 12345, "/help")
        assert handled is True
        assert mock_send.called
        assert "Anbar Ingestion Bot" in mock_send.call_args[0][2]

        mock_send.reset_mock()

        # 2. /status
        handled = await handle_bot_command(app, msg, "fake_token", 12345, "/status")
        assert handled is True
        assert mock_send.called
        assert "Anbar System Status" in mock_send.call_args[0][2]

        mock_send.reset_mock()

        # 3. /stats
        handled = await handle_bot_command(app, msg, "fake_token", 12345, "/stats")
        assert handled is True
        assert mock_send.called
        assert "Storage Distribution Breakdown" in mock_send.call_args[0][2]

        # 4. Unknown / non-command
        handled = await handle_bot_command(app, msg, "fake_token", 12345, "hello")
        assert handled is False
