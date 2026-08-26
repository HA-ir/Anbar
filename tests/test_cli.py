"""F4: anbarctl end-to-end against a live server (threaded uvicorn)."""

from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time

import uvicorn

from anbar.main import create_app


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _start_server():
    from anbar.storage import FakeBackend

    app = create_app(FakeBackend())
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    return f"http://127.0.0.1:{port}", server


def _run(base: str, *args) -> tuple[int, str]:
    cmd = [sys.executable, "-m", "anbar.cli", "--base-url", base, *args]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return p.returncode, p.stdout.strip()


def test_cli_auth_toggle_and_objects():
    base, server = _start_server()
    try:
        env_key = "test-admin-key"  # conftest sets ANBAR_ADMIN_KEY
        import os

        env = {**os.environ, "ANBAR_ADMIN_KEY": env_key}
        # version (no server needed)
        r = subprocess.run(
            [sys.executable, "-m", "anbar.cli", "version"],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        assert r.returncode == 0 and "anbar" in r.stdout

        # auth on -> off -> on
        rc, out = _run(base, "--admin-key", env_key, "auth", "off")
        assert rc == 0 and "OFF" in out, out
        rc, out = _run(base, "--admin-key", env_key, "auth", "on")
        assert rc == 0 and "ON" in out, out
        # idempotent
        rc, out = _run(base, "--admin-key", env_key, "auth", "on")
        assert rc == 0 and "already" in out.lower(), out

        # objects listing (empty)
        rc, out = _run(base, "--admin-key", env_key, "objects")
        assert rc == 0, out
    finally:
        server.should_exit = True
        time.sleep(0.2)
