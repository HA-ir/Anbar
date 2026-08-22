"""Flood management for large uploads (v0.8.3) — see README 'Why 1 GB...'."""
import asyncio

import httpx
import pytest

from anbar.storage import BotBackend, FloodBudgetExceeded, TelegramError

REAL_SLEEP = asyncio.sleep


def _stub_sleep(monkeypatch, log=None):
    """Replace asyncio.sleep with a no-op (record delays when `log` given).

    `bot_backend` calls asyncio.sleep by reference, so a module-level
    monkeypatch intercepts it without touching the event loop.
    """
    if log is None:
        monkeypatch.setattr(asyncio, "sleep", lambda d: REAL_SLEEP(0))
    else:
        def rec(d):
            log.append(d)
            return REAL_SLEEP(0)

        monkeypatch.setattr(asyncio, "sleep", rec)


def _ok(fid):
    return {"document": {"file_id": fid}}


def test_store_succeeds_first_try(monkeypatch):
    b = BotBackend("123:TEST", "-100999")
    b.send_gap_s = 0.0
    _stub_sleep(monkeypatch)

    async def main():
        calls = []

        async def fake_multipart(method, fields, files):
            calls.append(method)
            return _ok("f1")

        b._call_multipart = fake_multipart
        ref = await b.store(b"x" * 100, "a.bin")
        assert ref.file_id == "f1"
        assert calls == ["sendDocument"]

    asyncio.run(main())


def test_store_waits_out_429s_until_budget(monkeypatch):
    b = BotBackend("123:TEST", "-100999")
    b.send_gap_s = 0.0
    b.flood_budget_s = 60
    sleeps = []
    _stub_sleep(monkeypatch, sleeps)

    async def main():
        calls = {"n": 0}

        async def fake_multipart(method, fields, files):
            calls["n"] += 1
            if calls["n"] <= 3:  # three consecutive FloodWaits
                raise TelegramError(429, "Too Many Requests", retry_after=0)
            return _ok("f-ok")

        b._call_multipart = fake_multipart
        ref = await b.store(b"y" * 10, "b.bin")
        assert ref.file_id == "f-ok"
        assert calls["n"] == 4
        assert len(sleeps) == 3  # waited each 429 out

    asyncio.run(main())


def test_store_raises_flood_budget_exceeded(monkeypatch):
    b = BotBackend("123:TEST", "-100999")
    b.send_gap_s = 0.0
    b.flood_budget_s = 0  # zero budget → first 429 already over deadline
    _stub_sleep(monkeypatch)

    async def main():
        async def fake_multipart(method, fields, files):
            raise TelegramError(429, "Too Many Requests", retry_after=30)

        b._call_multipart = fake_multipart
        with pytest.raises(FloodBudgetExceeded) as ei:
            await b.store(b"z" * 10, "c.bin")
        assert ei.value.http_status == 504
        assert "try again later" in ei.value.message

    asyncio.run(main())


def test_store_non_flood_error_propagates_untouched(monkeypatch):
    b = BotBackend("123:TEST", "-100999")
    b.send_gap_s = 0.0
    _stub_sleep(monkeypatch)

    async def main():
        async def fake_multipart(method, fields, files):
            raise TelegramError(400, "chat not found")

        b._call_multipart = fake_multipart
        with pytest.raises(TelegramError) as ei:
            await b.store(b"w" * 10, "d.bin")
        assert isinstance(ei.value, TelegramError)
        assert not isinstance(ei.value, FloodBudgetExceeded)
        assert ei.value.code == 400

    asyncio.run(main())


def test_parse_missing_description_not_placeholder():
    """The old `telegram: ?` came from an empty Telegram description."""
    with pytest.raises(TelegramError) as ei:
        BotBackend._parse({"ok": False, "error": {"code": 502, "description": ""}})
    assert ei.value.message == "(no description)"
    assert "?" not in ei.value.message


def test_transport_error_maps_to_502(monkeypatch):
    b = BotBackend("123:TEST", "-100999")
    _stub_sleep(monkeypatch)

    async def main():
        async def boom(*a, **k):
            raise httpx.ConnectError("dial tcp: connection refused")

        b._http.post = boom
        with pytest.raises(TelegramError) as ei:
            await b._call("getMe")
        assert ei.value.http_status == 502
        assert "transport" in ei.value.message

    asyncio.run(main())


def test_pacing_queue_serialises_and_gaps(monkeypatch):
    """Two concurrent stores run one-after-another; the 2nd waits for a gap."""
    b = BotBackend("123:TEST", "-100999")
    b.send_gap_s = 5.0  # exaggerated; sleep itself is stubbed
    sleeps = []
    _stub_sleep(monkeypatch, sleeps)

    async def main():
        async def fake_multipart(method, fields, files):
            await REAL_SLEEP(0)  # yield so the 2nd task can start & block
            return _ok("p")

        b._call_multipart = fake_multipart
        results = await asyncio.gather(b.store(b"1", "a.bin"), b.store(b"2", "b.bin"))
        assert [r.file_id for r in results] == ["p", "p"]
        # the second send had to wait for the pacing gap (4.999... ≤ d < 5.0)
        assert any(d >= 4.9 for d in sleeps)

    asyncio.run(main())


def test_telegram_502_descriptionless_is_retried(monkeypatch):
    """The 1 GB bench died on a description-less 502 — it must be treated
    as transient and retried within the flood budget, not fatal."""
    b = BotBackend("123:TEST", "-100999")
    b.send_gap_s = 0.0
    _stub_sleep(monkeypatch)

    async def main():
        calls = {"n": 0}

        async def fake_multipart(method, fields, files):
            calls["n"] += 1
            if calls["n"] == 1:  # description-less 502, like the real bench
                raise TelegramError(502, "(no description)")
            return _ok("f-retry")

        b._call_multipart = fake_multipart
        ref = await b.store(b"t" * 10, "g.bin")
        assert ref.file_id == "f-retry"
        assert calls["n"] == 2

    asyncio.run(main())


def test_flood_budget_counts_cumulative_waits(monkeypatch):
    """Budget is cumulative across 429s, not per-retry."""
    b = BotBackend("123:TEST", "-100999")
    b.send_gap_s = 0.0
    b.flood_budget_s = 10
    _stub_sleep(monkeypatch)

    async def main():
        # each 429 asks to wait 30 s; budget is only 10 s → over after the
        # first wait is about to be applied
        with pytest.raises(FloodBudgetExceeded):
            async def fake_multipart(method, fields, files):
                raise TelegramError(429, "Too Many Requests", retry_after=30)

            b._call_multipart = fake_multipart
            await b.store(b"q" * 10, "e.bin")

    asyncio.run(main())


def test_stuck_send_hits_wall_clock_cap(monkeypatch):
    """A half-dead sendDocument (httpx per-op timeout never trips) must be
    hard-capped by wait_for and surface as a transient 502 (v0.8.4).

    This is the 500 MB wedge: chunk 29's POST never returned for 10+ min
    while the connection sat ESTAB; wait_for turns the infinite wedge into
    a retriable 502 the flood loop re-sends.
    """
    b = BotBackend("123:TEST", "-100999")
    b.send_timeout_s = 0.2  # tiny cap so the test is fast

    async def main():
        started = True

        async def frozen_post(*a, **k):  # never completes (stuck socket)
            nonlocal started
            assert started
            await REAL_SLEEP(3600)

        b._http.post = frozen_post
        with pytest.raises(TelegramError) as ei:
            await b._call_multipart(
                "sendDocument",
                fields={"chat_id": "-100999"},
                files={"document": ("big.part", b"x" * 10, "application/octet-stream")},
            )
        assert ei.value.http_status == 502
        assert "no response within" in ei.value.message
        # a transient 502 must be classified as rate-limitable so store()
        # retries the chunk instead of failing the whole upload
        assert b._is_rate_limited(ei.value)

    asyncio.run(main())