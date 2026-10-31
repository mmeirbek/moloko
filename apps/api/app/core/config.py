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

    # --- AI providers (official API keys only — spec 13.5) ---------------------
    # Optional fallbacks: a provider configured in the UI without its own key uses these.
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    provider_timeout_seconds: float = Field(120.0, gt=0)
    provider_max_retries: int = Field(2, ge=0, le=10)
    provider_retry_base_delay_seconds: float = Field(1.0, ge=0)
    # Deterministic offline provider for tests and demos. Never enable in production.
    enable_mock_provider: bool = False

    # --- Chat -----------------------------------------------------------------
    chat_context_max_messages: int = Field(40, ge=1, le=500)
    chat_max_output_tokens: int = Field(4096, ge=1)
    chat_title_max_chars: int = Field(60, ge=10, le=200)

    # --- Agent execution limits (spec 7.2; enforced in code, not prompts) -------
    max_active_subagents_per_run: int = Field(5, ge=1, le=50)
    max_subagent_depth: int = Field(2, ge=1, le=5)
    max_steps_per_run: int = Field(50, ge=1, le=1000)
    run_timeout_seconds: int = Field(1800, ge=10)
    max_retries_per_step: int = Field(2, ge=0, le=10)
    max_parallel_tool_calls: int = Field(3, ge=1, le=20)
    approval_ttl_minutes: int = Field(60, ge=1)
    agent_max_output_tokens: int = Field(4096, ge=1)

    # --- Worker (ARQ) ------------------------------------------------------------
    worker_max_jobs: int = Field(10, ge=1, le=100)
    # Queued tasks older than this are re-enqueued by the sweeper (duplicates are harmless).
    worker_requeue_after_seconds: int = Field(30, ge=5)
    # How often a running agent re-checks the DB for cancel/pause requests.
    worker_control_poll_seconds: float = Field(1.0, gt=0)

    # --- Realtime ------------------------------------------------------------------
    # Clients missing more events than this get a fresh snapshot instead of a replay.
    realtime_max_replay: int = Field(500, ge=10)
    realtime_heartbeat_seconds: float = Field(25.0, gt=0)

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
