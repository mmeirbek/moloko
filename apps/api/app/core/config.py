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
    max_subtasks_per_plan: int = Field(8, ge=1, le=50)
    agent_max_output_tokens: int = Field(4096, ge=1)

    # --- Memory (spec 17) ---------------------------------------------------------
    # Max characters of saved memory put into one agent's prompt (per-agent may be lower).
    memory_context_max_chars: int = Field(8000, ge=500, le=200_000)
    memory_entry_max_chars: int = Field(4000, ge=100, le=100_000)

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

    # --- Storage ---------------------------------------------------------------
    workspace_root: str = "/data/workspaces"
    file_storage_root: str = "/data/files"
    workspace_max_file_bytes: int = Field(1_000_000, ge=1000)  # one file read/written by a tool
    workspace_max_files: int = Field(5000, ge=10)  # files scanned per workspace
    # Task workspaces of finished tasks are deleted this many days later (0 = never).
    workspace_task_ttl_days: int = Field(14, ge=0)

    # --- Tools (spec 15) ----------------------------------------------------------
    tool_timeout_seconds: float = Field(60.0, gt=0, le=3600)
    tool_output_max_chars: int = Field(20_000, ge=500, le=500_000)

    # --- Sandbox (spec 16). The worker talks to the sandbox runner; only the runner
    # talks to Docker. Unset SANDBOX_URL = the terminal tool is unavailable.
    sandbox_url: str | None = None
    sandbox_runner_token: SecretStr | None = None
    sandbox_image: str = "python:3.12.16-slim"
    sandbox_cpus: float = Field(1.0, gt=0, le=16)
    sandbox_memory_mb: int = Field(512, ge=64, le=65_536)
    sandbox_pids_limit: int = Field(128, ge=16, le=4096)
    sandbox_timeout_seconds: int = Field(60, ge=1, le=3600)
    sandbox_allowed_commands: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "python",
            "python3",
            "pip",
            "pytest",
            "ls",
            "cat",
            "head",
            "tail",
            "wc",
            "grep",
            "find",
            "sort",
            "uniq",
            "diff",
            "echo",
            "mkdir",
            "touch",
            "cp",
            "mv",
            "sed",
            "awk",
            "tar",
            "gzip",
            "gunzip",
            "unzip",
            "git",
            "make",
            "node",
            "npm",
            "npx",
        ]
    )
    # Runner side: how sandbox containers get the workspace (a named volume in compose,
    # or a host directory for development).
    sandbox_workspaces_volume: str | None = "moloko_workspaces"
    sandbox_workspaces_host_path: str | None = None
    docker_socket: str = "/var/run/docker.sock"

    # --- Web (spec 15.6 Browser) ---------------------------------------------------------
    web_fetch_timeout_seconds: float = Field(20.0, gt=0, le=120)
    web_fetch_max_bytes: int = Field(2_000_000, ge=10_000, le=50_000_000)
    web_fetch_allowed_ports: Annotated[list[int], NoDecode] = Field(
        default_factory=lambda: [80, 443]
    )
    searxng_url: str | None = None  # optional self-hosted search; unset = no web_search

    # --- Integrations ----------------------------------------------------------------
    integration_timeout_seconds: float = Field(20.0, gt=0, le=120)
    mcp_timeout_seconds: float = Field(30.0, gt=0, le=600)

    @field_validator("secret_key")
    @classmethod
    def _secret_key_strength(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError(
                "SECRET_KEY must be at least 32 characters (use: openssl rand -hex 32)"
            )
        return value

    @field_validator("sandbox_url", "sandbox_runner_token", "searxng_url", mode="before")
    @classmethod
    def _empty_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator(
        "cors_allowed_origins", "sandbox_allowed_commands", "web_fetch_allowed_ports", mode="before"
    )
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
