"""Configuration: env-driven, validated, immutable."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Backend(StrEnum):
    BOT = "bot"
    MTPROTO = "mtproto"  # reserved for F5
    FAKE = "fake"  # in-memory, for local dev & CI smoke tests


class ChunkingMode(StrEnum):
    AUTO = "auto"
    OFF = "off"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
    env_prefix="ANBAR_", env_file=".env", extra="ignore", env_ignore_empty=True
)

    # server
    host: str = "0.0.0.0"
    port: int = Field(default=8567, ge=1, le=65535)
    base_url: str = "http://127.0.0.1:8567"  # used to build returned links
    log_level: str = Field(default="INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR)$")

    # storage
    backend: Backend = Backend.BOT
    bot_token: SecretStr | None = None
    bot_tokens_raw: str | None = Field(default=None, alias="ANBAR_BOT_TOKENS")
    channel_id: str = ""  # private channel the bot administers (backend=bot)
    channel_thread_id: int | None = None  # Forum topic message_thread_id (v0.11)
    api_id: int | None = None
    api_hash: str = ""
    session_file: Path = Path("secrets/session.session")
    mtproto_peer: str = "me"  # destination entity for mtproto blobs ("me"=Saved)

    # limits
    max_upload_mb: int = Field(default=10240, ge=1)

    # chunking (v1.1)
    chunking: ChunkingMode = ChunkingMode.AUTO
    chunk_size_mb: int = Field(default=16, ge=1)
    mtproto_chunk_cap_mb: int = Field(default=49, ge=1)

    # flood pacing (v0.8.3, bot backend)
    flood_send_gap_s: float = Field(default=1.1, ge=0)  # min gap between sends
    flood_budget_s: float = Field(default=2400, ge=10)  # max cumulative 429 waits
    # wall-clock cap per sendDocument (v0.8.4) — see bot_backend module docstring
    send_timeout_s: float = Field(default=300, ge=5)
    # client body-stall cap (v0.8.4): abort upload if no bytes arrive this long
    body_idle_timeout_s: float = Field(default=300, ge=5)
    # URL ingest (v0.8.5): per-request timeout for pulling from the origin
    ingest_read_timeout_s: float = Field(default=600, ge=30)

    # auth
    admin_key: SecretStr | None = None
    api_key: SecretStr | None = None
    hmac_secret: SecretStr | None = None
    auth_enabled: bool = True

    # rate limiting (F6; 0 disables a limiter)
    rate_download_per_min: int = Field(default=10, ge=0)
    rate_upload_per_min: int = Field(default=5, ge=0)
    rate_login_per_min: int = Field(default=10, ge=0)

    # web UI sessions (F7)
    web_session_ttl: int = Field(default=43200, ge=300)  # 12 h

    # cache
    cache_enabled: bool = False
    cache_dir: Path = Path("data/cache")
    cache_max_mb: int = Field(default=512, ge=0)

    # mtproto download acceleration (FastTelethon-style exported auth)
    mtproto_export_conns: int = Field(default=0, ge=0, le=8)  # 0 = off

    # hybrid store (v0.12.0)
    hybrid_enabled: bool = False
    hybrid_bot_timeout_s: float = Field(default=1.5, ge=0.2, le=30.0)

    # auto daily database backup to telegram (v0.15.0)
    auto_backup_enabled: bool = True

    # PERF-01: RAM budget (MB) for the per-chunk seek micro cache; 0 = off
    seek_cache_mb: int = Field(default=32, ge=0)

    @property
    def bot_tokens(self) -> list[str]:
        """List of all available bot tokens (pool)."""
        tokens: list[str] = []
        if self.bot_tokens_raw:
            tokens.extend(t.strip() for t in self.bot_tokens_raw.split(",") if t.strip())
        if self.bot_token:
            val = self.bot_token.get_secret_value().strip()
            if val and val not in tokens:
                tokens.append(val)
        return tokens

    # data
    data_dir: Path = Path("data")
    db_path: Path = Path("data/anbar.db")

    @field_validator("base_url")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.rstrip("/")

    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def chunk_size(self) -> int:
        """Effective chunk size in bytes (capped by the backend's send limit).

        bot: 19 MB (Bot API ceiling is 20 MB).
        mtproto: capped by `mtproto_chunk_cap_mb` (default 49 MB; Telegram
        itself allows up to 2 GB per file, so this is a tunable knob).
        fake: 19 MB (mirrors the bot contract).
        """
        size = self.chunk_size_mb * 1024 * 1024
        cap = (
            self.mtproto_chunk_cap_mb * 1024 * 1024
            if self.backend is Backend.MTPROTO
            else 19 * 1024 * 1024
        )
        return min(size, cap)


@lru_cache
def get_settings() -> Settings:
    return Settings()
