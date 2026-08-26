"""anbarctl put/get round-trip end-to-end (threaded uvicorn + real files)."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import threading
import time

import uvicorn

from anbar.main import create_app


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getnameinfo()[1] if False else s.getsockname()[1]
    s.close()
    return port


def _run(base: str, key: str, *args, timeout: int = 30):
    env = {**os.environ, "ANBAR_BASE_URL": base, "ANBAR_ADMIN_KEY": key}
    return subprocess.run(
        [sys.executable, "-m", "anbar.cli", "--base-url", base, "--admin-key", key, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def test_cli_put_get_roundtrip(monkeypatch):
    from anbar.storage import FakeBackend

    # link URLs are built from settings.base_url; point it at our live port
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    monkeypatch.setenv("ANBAR_BASE_URL", f"http://127.0.0.1:{port}")
    app = create_app(FakeBackend())
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    base = f"http://127.0.0.1:{port}"
    key = "test-admin-key"
    try:
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "hello.txt")
        payload = b"anbarctl roundtrip \xe2\x9c\x93"
        with open(src, "wb") as f:
            f.write(payload)
        r = _run(base, key, "put", src)
        assert r.returncode == 0, r.stderr
        oid = r.stdout.split()[1]

        out = os.path.join(tmp, "out.bin")
        r = _run(base, key, "get", oid, "-o", out, timeout=60)
        assert r.returncode == 0, r.stderr
        with open(out, "rb") as f:
            assert f.read() == payload
    finally:
        server.should_exit = True
        thread.join(timeout=5)
