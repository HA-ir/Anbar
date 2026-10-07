"""Tests for anbarctl webhook CLI commands."""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

from anbar.cli import main


def test_cli_webhook_set():
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(
        {"ok": True, "description": "Webhook was set"}
    ).encode()

    class _Context:
        def __enter__(self):
            return mock_resp

        def __exit__(self, *args):
            pass

    with (
        patch("urllib.request.urlopen", return_value=_Context()) as mock_open,
        patch("sys.stdout", new_callable=io.StringIO) as mock_out,
    ):
        code = main(
            [
                "webhook",
                "set",
                "https://example.com/api/v1/tg/webhook",
                "--token",
                "123:ABC",
                "--secret",
                "secret123",
            ]
        )
        assert code == 0
        assert mock_open.called
        req = mock_open.call_args[0][0]
        assert "api.telegram.org/bot123:ABC/setWebhook" in req.full_url
        payload = json.loads(req.data.decode())
        assert payload["url"] == "https://example.com/api/v1/tg/webhook"
        assert payload["secret_token"] == "secret123"
        assert "Webhook set successfully" in mock_out.getvalue()


def test_cli_webhook_info():
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(
        {
            "ok": True,
            "result": {
                "url": "https://example.com/api/v1/tg/webhook",
                "has_custom_certificate": False,
                "pending_update_count": 0,
            },
        }
    ).encode()

    class _Context:
        def __enter__(self):
            return mock_resp

        def __exit__(self, *args):
            pass

    with (
        patch("urllib.request.urlopen", return_value=_Context()),
        patch("sys.stdout", new_callable=io.StringIO) as mock_out,
    ):
        code = main(["webhook", "info", "--token", "123:ABC"])
        assert code == 0
        output = mock_out.getvalue()
        assert "Webhook Info:" in output
        assert "https://example.com/api/v1/tg/webhook" in output


def test_cli_webhook_delete():
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(
        {"ok": True, "description": "Webhook was deleted"}
    ).encode()

    class _Context:
        def __enter__(self):
            return mock_resp

        def __exit__(self, *args):
            pass

    with (
        patch("urllib.request.urlopen", return_value=_Context()),
        patch("sys.stdout", new_callable=io.StringIO) as mock_out,
    ):
        code = main(["webhook", "delete", "--token", "123:ABC"])
        assert code == 0
        assert "Webhook deleted" in mock_out.getvalue()
