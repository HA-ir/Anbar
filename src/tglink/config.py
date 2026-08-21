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
    model_config = SettingsConfigDict(env_prefix="TGLINK_", env_file=".env", extra="ignore")

    # server
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    base_url: str = "http://127.0.0.1:8000"  # used to build returned links

    # storage
    backend: Backend = Backend.BOT
    bot_token: SecretStr | None = None
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

    # cache
    cache_enabled: bool = False
    cache_dir: Path = Path("data/cache")
    cache_max_mb: int = Field(default=512, ge=0)

    # data
    data_dir: Path = Path("data")
    db_path: Path = Path("data/tglink.db")

    @field_validator("base_url")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.rstrip("/")

    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()