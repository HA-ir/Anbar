"""v0.15.36b — ANBAR_<INT>= (empty) in .env must not crash Settings boot."""


def test_empty_int_env_is_none(monkeypatch):
    from anbar.config import Settings

    monkeypatch.setenv("ANBAR_CHANNEL_THREAD_ID", "")
    s = Settings(_env_file=None)
    assert s.channel_thread_id is None


def test_nonempty_int_env_still_parses(monkeypatch):
    from anbar.config import Settings

    monkeypatch.setenv("ANBAR_CHANNEL_THREAD_ID", "777")
    s = Settings(_env_file=None)
    assert s.channel_thread_id == 777
