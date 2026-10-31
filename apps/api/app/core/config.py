"""Application settings.

Everything configurable lives here and is read from environment variables
(spec section 7). Nothing in the codebase may hardcode hostnames, secrets or limits.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "moloko"
    environment: Literal["development", "test", "production"] = "production"
    log_level: str = "INFO"

    # --- Data stores ---------------------------------------------------------
    database_url: str = Field(description="postgresql+asyncpg://user:pass@host:5432/db")
    redis_url: str = Field(description="redis://host:6379/0")
    db_pool_size: int = Field(5, ge=1, le=50)
    db_max_overflow: int = Field(5, ge=0, le=50)

    # --- Secrets -------------------------------------------------------------
    secret_key: SecretStr = Field(description="Signs CSRF tokens. At least 32 characters.")
    # Encrypts provider credentials at rest. Required from Sprint 2 (providers).
    app_encryption_key: SecretStr | None = None

    # --- Sessions / cookies ---------------------------------------------------
    session_ttl_hours: int = Field(168, ge=1, le=24 * 90)
    session_touch_interval_seconds: int = Field(300, ge=0)
    session_cookie_name: str = "moloko_session"
    csrf_cookie_name: str = "moloko_csrf"
    csrf_header_name: str = "X-CSRF-Token"
    # Must stay true behind Tailscale Serve (HTTPS). Set false only for plain-http local dev.
    cookie_secure: bool = True

    # --- Login brute-force protection ----------------------------------------
    login_max_failures: int = Field(5, ge=1)
    login_lockout_seconds: int = Field(900, ge=1)

    # --- HTTP ----------------------------------------------------------------
    # Comma-separated. Empty = same-origin only (the default behind the reverse proxy).
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # --- Storage (used from later sprints) ------------------------------------
    workspace_root: str = "/data/workspaces"
    file_storage_root: str = "/data/files"

    @field_validator("secret_key")
    @classmethod
    def _secret_key_strength(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError(
                "SECRET_KEY must be at least 32 characters (use: openssl rand -hex 32)"
            )
        return value

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment
