"""Application settings.

Everything configurable lives here and is read from environment variables
(spec section 7). Nothing in the codebase may hardcode hostnames, secrets or limits.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# A DNS name (labels of letters, digits and hyphens) — what WebAuthn accepts as an RP ID.
_LABEL = r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?"
_HOSTNAME_RE = re.compile(rf"^(?=.{{1,253}}$){_LABEL}(\.{_LABEL})*$")
_IPV4_RE = re.compile(r"^\d+(\.\d+){3}$")


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
    # How long a sign-in lasts (absolute expiry). The owner may choose their own value
    # within [min, max] (confirmed with the password); this is the default.
    session_ttl_hours: int = Field(168, ge=1, le=24 * 90)
    session_ttl_min_hours: int = Field(1, ge=1, le=24 * 90)
    session_ttl_max_hours: int = Field(24 * 90, ge=1, le=24 * 90)
    session_touch_interval_seconds: int = Field(300, ge=0)
    session_cookie_name: str = "moloko_session"
    csrf_cookie_name: str = "moloko_csrf"
    csrf_header_name: str = "X-CSRF-Token"
    # Must stay true behind Tailscale Serve (HTTPS). Set false only for plain-http local dev.
    cookie_secure: bool = True

    # --- Login brute-force protection ----------------------------------------
    login_max_failures: int = Field(5, ge=1)
    login_lockout_seconds: int = Field(900, ge=1)

    # --- Passkeys (WebAuthn: sign in with Face ID / Touch ID) --------------------
    # The site's domain exactly as the browser shows it, without scheme or port, e.g.
    # moloko.tail1234.ts.net, and the full origin(s), e.g. https://moloko.tail1234.ts.net
    # (comma-separated). Both empty = passkeys off, password only — e.g. on an
    # http://127.0.0.1 test stack: WebAuthn needs a real domain name.
    webauthn_rp_id: str | None = None
    webauthn_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Shown by the device when it saves the passkey ("moloko — owner").
    webauthn_rp_name: str = Field("moloko", min_length=1, max_length=64)
    # How long one passkey prompt stays valid. Its challenge is single-use.
    webauthn_challenge_ttl_seconds: int = Field(300, ge=30, le=900)
    webauthn_max_credentials: int = Field(20, ge=1, le=100)
    # Short-lived cookie that binds a sign-in prompt to the browser that asked for it.
    webauthn_cookie_name: str = "moloko_passkey"

    # --- Owner profile ----------------------------------------------------------
    # Longest form of address the owner may set (users.address_as). It goes into the
    # instruction part of every prompt that talks to the owner, so it stays short.
    address_as_max_chars: int = Field(80, ge=10, le=500)

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
    # Attached files: any type, any size, any number (0 = no limit). The original is
    # streamed to FILE_STORAGE_ROOT; what the model sees is cut to a budget (below).
    chat_attachment_max_bytes: int = Field(0, ge=0)
    chat_attachments_per_message: int = Field(0, ge=0)
    # Uploads stop (507) when the disk would have less free space than this.
    chat_upload_min_free_bytes: int = Field(1_000_000_000, ge=0)
    # Text kept in the database per file (decoded text / PDF text) for prompts and search.
    chat_attachment_text_max_chars: int = Field(2_000_000, ge=1000, le=50_000_000)
    # Pages read from a PDF (0 = all) and the time allowed for it; the file is kept anyway.
    chat_pdf_max_pages: int = Field(0, ge=0)
    chat_pdf_timeout_seconds: float = Field(60.0, gt=0, le=3600)
    # Attachment text put into one model request (all files, newest message first). It is
    # also capped at CHAT_ATTACHMENT_CONTEXT_SHARE of the model's context window when the
    # model config says how big it is (params.context_window, in tokens).
    chat_attachment_prompt_max_chars: int = Field(200_000, ge=1000, le=20_000_000)
    chat_attachment_context_share: float = Field(0.5, gt=0, le=0.9)
    chat_chars_per_token: float = Field(3.0, gt=0.5, le=10)
    # Pictures are sent to vision models at most this big (longest side, bytes); larger
    # ones get a downscaled copy for the model, the original is kept. Bigger than
    # CHAT_IMAGE_MAX_PIXELS = not decoded at all (shown to the model as a note).
    chat_image_model_max_side: int = Field(1568, ge=256, le=8000)
    chat_image_model_max_bytes: int = Field(3_500_000, ge=100_000, le=20_000_000)
    chat_image_max_pixels: int = Field(100_000_000, ge=1_000_000, le=1_000_000_000)
    chat_image_timeout_seconds: float = Field(60.0, gt=0, le=600)
    # How many of the most recent pictures in a chat are sent to the model again, and the
    # most pictures sent in one request (the rest are listed by name).
    chat_context_images: int = Field(4, ge=0, le=20)
    chat_images_per_request: int = Field(20, ge=1, le=100)
    # A long chat never forgets: messages that no longer fit into CHAT_CONTEXT_MAX_MESSAGES
    # are condensed into a rolling summary (stored on the conversation, made in the
    # background after an answer). CHAT_SUMMARY_MODEL = the name of one of your models
    # (e.g. a cheaper one); empty = the chat's own model. INPUT_MAX_CHARS = how much new
    # conversation text one summary call reads.
    # The chat hands work (code, repositories, commands, websites, several steps) to the
    # agents by itself; questions it answers itself.
    chat_auto_handoff: bool = True
    # The chat always reads the shared memory about the owner (pinned first) and uses it quietly.
    chat_pinned_memory: bool = True
    chat_summary_enabled: bool = True
    chat_summary_max_chars: int = Field(4000, ge=500, le=50_000)
    chat_summary_model: str = ""
    chat_summary_input_max_chars: int = Field(30_000, ge=2000, le=500_000)
    # Recall: before answering, the best matches from the owner's other chats, tasks and
    # memory (through search) are given to the model as data. TYPES = search source types.
    chat_recall_enabled: bool = True
    chat_recall_top_k: int = Field(5, ge=1, le=20)
    chat_recall_max_chars: int = Field(3000, ge=200, le=20_000)
    chat_recall_timeout_seconds: float = Field(2.0, gt=0, le=30)
    chat_recall_types: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "memory",
            "attachment",
            "task",
            "chat_message",
            "agent_message",
        ]
    )

    # --- Agent execution limits (spec 7.2; enforced in code, not prompts) -------
    # Parts of one Orchestrator plan running at the same time (each on one of the agents).
    max_active_parts_per_run: int = Field(5, ge=1, le=50)
    # Plans the Orchestrator runs at once (it is free while the agents do the parts); more
    # tasks wait in line and start by themselves.
    orchestrator_max_tasks_at_once: int = Field(5, ge=1, le=50)
    # New agents the Orchestrator may create in one plan when none of the owner's fits
    # (they join the office and stay); 0 = it only uses the owner's agents.
    orchestrator_max_new_agents: int = Field(3, ge=0, le=10)
    # How many of the owner's models the Orchestrator sees when it plans (strongest first).
    orchestrator_max_models_listed: int = Field(40, ge=0, le=500)
    max_steps_per_run: int = Field(50, ge=1, le=1000)
    run_timeout_seconds: int = Field(1800, ge=10)
    max_retries_per_step: int = Field(2, ge=0, le=10)
    max_parallel_tool_calls: int = Field(3, ge=1, le=20)
    approval_ttl_minutes: int = Field(60, ge=1)
    max_subtasks_per_plan: int = Field(8, ge=1, le=50)
    # Longest reply an agent's model may write in one step (a model's own `max_tokens` param
    # wins). Code and documents need room: 4096 cut files off mid-way. A reply that still
    # hits the limit is not executed; the agent is told to continue in smaller parts, at
    # most AGENT_MAX_CUT_OFFS times in a row before the task fails with `output_truncated`.
    agent_max_output_tokens: int = Field(16_000, ge=256, le=200_000)
    agent_max_cut_offs: int = Field(3, ge=0, le=20)
    # Replying in a finished task's chat continues it: an agent without a saved conversation
    # (the Orchestrator) gets its earlier answers (fenced as data) and the owner's replies —
    # at most this many turns, each answer cut to this many characters.
    task_followup_turns: int = Field(5, ge=1, le=50)
    # The milk bottle of a working agent: half full after this many steps (an estimate).
    task_progress_half_steps: int = Field(4, ge=1, le=100)
    task_followup_answer_max_chars: int = Field(8000, ge=500, le=200_000)
    # Per-agent monthly budgets: the owner is warned when an agent has spent this share of
    # its own limit; at 100 % its new model calls are refused.
    agent_budget_warn_percent: int = Field(80, ge=10, le=99)
    # How many own templates ("Save as template") the owner may keep.
    agent_templates_max: int = Field(50, ge=1, le=1000)
    # Agents talking to each other directly (agent_ask / agent_tell, no Orchestrator):
    # how long an asking agent waits for the answer, how deep a chain A→B→C… may go,
    # how many questions one task may ask, and the size of one message and its files.
    agent_ask_timeout_minutes: int = Field(30, ge=1, le=24 * 60)
    agent_ask_max_hops: int = Field(3, ge=1, le=10)
    agent_asks_per_task: int = Field(10, ge=1, le=100)
    agent_message_max_chars: int = Field(20_000, ge=500, le=200_000)
    agent_message_max_files: int = Field(10, ge=0, le=100)

    # --- Memory (spec 17) ---------------------------------------------------------
    # Max characters of saved memory put into one agent's prompt (per-agent may be lower).
    memory_context_max_chars: int = Field(8000, ge=500, le=200_000)
    memory_entry_max_chars: int = Field(4000, ge=100, le=100_000)
    # "Your recent work" in every agent's prompt (owner request: agents remember what they
    # did): how many of its last finished tasks, and at most how many characters in all.
    # 0 = off.
    work_history_items: int = Field(10, ge=0, le=100)
    work_history_context_chars: int = Field(4000, ge=0, le=50_000)

    # --- Worker (ARQ) ------------------------------------------------------------
    worker_max_jobs: int = Field(10, ge=1, le=100)
    # Queued tasks older than this are re-enqueued by the sweeper (duplicates are harmless).
    worker_requeue_after_seconds: int = Field(30, ge=5)
    # How often a running agent re-checks the DB for cancel/pause requests.
    worker_control_poll_seconds: float = Field(1.0, gt=0)

    # --- Scheduled tasks (owner request) ---------------------------------------------
    # How many schedules one owner may keep, and the shortest repeat ("every N hours").
    schedules_max_per_user: int = Field(50, ge=1, le=1000)
    schedule_min_interval_minutes: int = Field(60, ge=60, le=1440)
    # A due schedule whose agent is busy waits this long for it (checked every tick), then
    # that run is skipped. 0 = skip at once.
    schedule_busy_wait_minutes: int = Field(30, ge=0, le=720)
    # Due schedules started per worker tick (the rest follow on the next tick).
    schedule_due_batch: int = Field(20, ge=1, le=500)

    # --- Realtime ------------------------------------------------------------------
    # Clients missing more events than this get a fresh snapshot instead of a replay.
    realtime_max_replay: int = Field(500, ge=10)
    realtime_heartbeat_seconds: float = Field(25.0, gt=0)

    # --- Storage ---------------------------------------------------------------
    workspace_root: str = "/data/workspaces"
    file_storage_root: str = "/data/files"
    workspace_max_file_bytes: int = Field(1_000_000, ge=1000)  # one file read/written by a tool
    workspace_max_files: int = Field(20_000, ge=10)  # files scanned per workspace
    # Folders whose files a command's change list skips (installed packages, caches, build
    # output, git internals): `npm ci` must not flood the file records, the search index or
    # the scan limit above. They stay in the workspace and are still listed and readable.
    workspace_untracked_dirs: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "node_modules",
            ".git",
            ".next",
            ".cache",
            ".turbo",
            "__pycache__",
            ".venv",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
        ]
    )
    # Task workspaces of finished tasks are deleted this many days later (0 = never, the
    # default: the work of agents is kept). The task records stay in PostgreSQL either way.
    workspace_task_ttl_days: int = Field(0, ge=0)

    # Where the backup service writes (mounted read-only into the backend for its status).
    backup_dir: str = "/backups"
    backup_max_age_hours: int = Field(36, ge=1)
    # Warn when the last good off-site copy (offsite-last.json in backup_dir) is older.
    offsite_max_age_hours: int = Field(48, ge=1)
    disk_warn_free_percent: float = Field(10.0, ge=0, le=90)

    # --- Tools (spec 15) ----------------------------------------------------------
    tool_timeout_seconds: float = Field(60.0, gt=0, le=3600)
    tool_output_max_chars: int = Field(20_000, ge=500, le=500_000)

    # --- Sandbox (spec 16). The worker talks to the sandbox runner; only the runner
    # talks to Docker. Unset SANDBOX_URL = the terminal tool is unavailable.
    sandbox_url: str | None = None
    sandbox_runner_token: SecretStr | None = None
    # Python 3.12 + Node.js 22 + git (infrastructure/docker/sandbox-runner.Dockerfile).
    sandbox_image: str = "moloko-sandbox:local"
    sandbox_cpus: float = Field(1.0, gt=0, le=16)
    # Room for `npm ci`, a type check and a Next.js build (512 MB / 128 were too small).
    sandbox_memory_mb: int = Field(2048, ge=64, le=65_536)
    sandbox_pids_limit: int = Field(512, ge=16, le=4096)
    # The longest one command may run; a command that does not say runs at most
    # SANDBOX_DEFAULT_TIMEOUT_SECONDS (so a hung program does not hold the agent for long).
    sandbox_timeout_seconds: int = Field(600, ge=1, le=3600)
    sandbox_default_timeout_seconds: int = Field(120, ge=1, le=3600)
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
    # `terminal_run` with network "packages" may reach only these hosts (HTTPS, through the
    # `egress-packages` proxy, which gets the same list; public addresses only).
    # cdn.playwright.dev / playwright.download.prss.microsoft.com: Playwright's browser builds
    # (`npx playwright install chromium` for browser tests).
    sandbox_package_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "registry.npmjs.org",
            "pypi.org",
            "files.pythonhosted.org",
            "cdn.playwright.dev",
            "playwright.download.prss.microsoft.com",
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
    # --- Voice input: the local Whisper service first (no key, no cost), else the
    # owner's OpenAI provider. Empty STT_URL = no local service.
    stt_url: str | None = None
    # --- Codex signed in with the owner's ChatGPT account (service `codex`, owner's decision
    # 2026-11-04). Unset CODEX_URL = off. Agents whose model is a Codex model run through it.
    codex_url: str | None = None
    codex_service_token: SecretStr | None = None
    codex_run_timeout_seconds: int = Field(3600, ge=60, le=86_400)
    stt_model: str = "large-v3-turbo"  # must match the `stt` service's STT_MODEL
    stt_timeout_seconds: float = Field(900.0, gt=0, le=7200)  # a 15-minute recording
    stt_connect_timeout_seconds: float = Field(3.0, gt=0, le=60)
    stt_health_cache_seconds: float = Field(15.0, ge=0, le=600)
    # Largest recording accepted, and the provider API's own cap (OpenAI: 25 MB).
    voice_upload_max_bytes: int = Field(200_000_000, ge=10_000, le=2_000_000_000)
    transcription_provider_max_bytes: int = Field(25_000_000, ge=10_000)
    # --- Semantic search and provider voice (through the owner's OpenAI provider) ----
    # Model names are defaults; the owner can change them in Settings → Voice & search.
    transcription_model: str = "gpt-4o-mini-transcribe"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(1536, ge=64, le=4096)
    search_chunk_chars: int = Field(1200, ge=200, le=8000)
    search_max_results: int = Field(8, ge=1, le=50)
    search_index_batch: int = Field(32, ge=1, le=256)
    # Work history in search (finished tasks, agent↔agent messages, chat messages): how
    # many of them are (re)indexed per pass (a backfill goes newest first, a pass at a
    # time, so the worker never stalls) and how many chunks one of them may take.
    work_index_batch: int = Field(100, ge=1, le=2000)
    work_index_max_chunks: int = Field(20, ge=1, le=200)
    # --- Web Push (notifications while the app is closed) ---------------------------
    # Contact for the push services (VAPID "sub"): mailto:you@your-domain or an https:// URL.
    # While it is the placeholder, the site's own address (WEBAUTHN_ORIGINS) is used: Apple
    # refuses placeholder contacts.
    push_contact: str = "mailto:owner@moloko.invalid"
    push_ttl_seconds: int = Field(86_400, ge=60, le=2_419_200)
    # Subscriptions may only point to these push services (no requests to anything else).
    push_allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "fcm.googleapis.com",
            "*.push.services.mozilla.com",
            "updates.push.services.mozilla.com",
            "web.push.apple.com",
            "*.notify.windows.com",
        ]
    )

    # github_checkout: a repository unpacked into the workspace (archive and its files).
    github_checkout_max_bytes: int = Field(300_000_000, ge=1_000_000, le=10_000_000_000)
    github_checkout_max_files: int = Field(10_000, ge=10, le=200_000)
    # github_commit_files: files in one commit, and their total size.
    github_commit_max_files: int = Field(300, ge=1, le=5000)
    github_commit_max_bytes: int = Field(20_000_000, ge=10_000, le=500_000_000)
    # How long one checkout or multi-file commit may take in all.
    github_transfer_timeout_seconds: float = Field(300.0, gt=0, le=3600)

    # The official GitHub MCP server (github/github-mcp-server, hosted by GitHub).
    github_mcp_url: str = "https://api.githubcopilot.com/mcp/"

    @field_validator("secret_key")
    @classmethod
    def _secret_key_strength(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError(
                "SECRET_KEY must be at least 32 characters (use: openssl rand -hex 32)"
            )
        return value

    @field_validator(
        "sandbox_url",
        "sandbox_runner_token",
        "searxng_url",
        "webauthn_rp_id",
        "stt_url",
        "codex_url",
        "codex_service_token",
        mode="before",
    )
    @classmethod
    def _empty_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator(
        "cors_allowed_origins",
        "sandbox_allowed_commands",
        "sandbox_package_hosts",
        "workspace_untracked_dirs",
        "web_fetch_allowed_ports",
        "push_allowed_hosts",
        "webauthn_origins",
        "chat_recall_types",
        mode="before",
    )
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _session_ttl_within_bounds(self) -> Self:
        if not (self.session_ttl_min_hours <= self.session_ttl_hours <= self.session_ttl_max_hours):
            raise ValueError(
                "SESSION_TTL_HOURS must lie between SESSION_TTL_MIN_HOURS and SESSION_TTL_MAX_HOURS"
            )
        return self

    @model_validator(mode="after")
    def _webauthn_consistent(self) -> Self:
        """Passkeys need both the RP ID and its origins; each origin must be an HTTPS origin
        (http only for localhost) on the RP ID or one of its subdomains. A wrong value
        fails at startup instead of failing silently in the browser."""
        if self.webauthn_rp_id is None and not self.webauthn_origins:
            return self
        if self.webauthn_rp_id is None or not self.webauthn_origins:
            raise ValueError("Set both WEBAUTHN_RP_ID and WEBAUTHN_ORIGINS, or neither")
        rp_id = self.webauthn_rp_id.strip().lower().rstrip(".")
        if not _HOSTNAME_RE.fullmatch(rp_id) or _IPV4_RE.fullmatch(rp_id):
            raise ValueError(
                "WEBAUTHN_RP_ID must be a domain name without scheme or port, "
                "e.g. moloko.tail1234.ts.net"
            )
        origins: list[str] = []
        for raw in self.webauthn_origins:
            origin = raw.strip().rstrip("/").lower()
            parsed = urlsplit(origin)
            host = parsed.hostname or ""
            secure = parsed.scheme == "https" or (parsed.scheme == "http" and host == "localhost")
            if (
                not secure
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username is not None
                or not (host == rp_id or host.endswith("." + rp_id))
            ):
                raise ValueError(
                    f"WEBAUTHN_ORIGINS: {raw!r} must be an https:// origin on {rp_id} "
                    "(no path), e.g. https://" + rp_id
                )
            origins.append(origin)
        self.webauthn_rp_id = rp_id
        self.webauthn_origins = origins
        return self

    @property
    def passkeys_enabled(self) -> bool:
        return self.webauthn_rp_id is not None and bool(self.webauthn_origins)

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment
