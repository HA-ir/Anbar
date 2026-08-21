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
    model_config = SettingsConfigDict(env_prefix="ANBAR_", env_file=".env", extra="ignore")

    # server
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    base_url: str = "http://127.0.0.1:8000"  # used to build returned links

    # storage
    backend: Backend = Backend.BOT
    bot_token: SecretStr | None = None
    channel_id: str = ""  # private channel the bot administers (backend=bot)
    api_id: int | None = None
    api_hash: str = ""
    session_file: Path = Path("secrets/session.session")

    # limits
    max_upload_mb: int = Field(default=2000, ge=1)

    # chunking (v1.1)
    chunking: ChunkingMode = ChunkingMode.AUTO
    chunk_size_mb: int = Field(default=16, ge=1, le=1024)

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
        mtproto: 49 MB (larger blobs → fewer messages; Telethon handles any
        size up to 2 GB per file, so this is a tunable efficiency knob).
        fake: 19 MB (mirrors the bot contract).
        """
        size = self.chunk_size_mb * 1024 * 1024
        cap = 49 * 1024 * 1024 if self.backend is Backend.MTPROTO else 19 * 1024 * 1024
        return min(size, cap)


@lru_cache
def get_settings() -> Settings:
    return Settings()