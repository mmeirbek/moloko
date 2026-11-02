from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.tools.base import ToolCategory


class ToolOut(BaseModel):
    name: str
    title: str
    description: str
    group: str
    category: str
    source: Literal["builtin", "mcp"]
    server_id: uuid.UUID | None = None
    server_name: str | None = None
    enabled: bool
    available: bool
    input_schema: dict[str, Any]


class ToolUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    category: ToolCategory | None = None  # MCP tools only: the owner classifies them


class ApprovalOut(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str | None
    task_id: uuid.UUID
    run_id: uuid.UUID
    tool_name: str
    category: str
    args: dict[str, Any]
    summary: str
    resources: list[str]
    consequences: str
    reason: str
    status: str
    expires_at: datetime
    created_at: datetime | None
    resolved_at: datetime | None


class ToolCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    agent_id: uuid.UUID
    step: int
    tool_name: str
    category: str | None
    args: dict[str, Any]
    decision: str | None
    decision_reason: str | None
    approval_id: uuid.UUID | None
    status: str
    result: str | None
    is_error: bool
    duration_ms: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class GitHubIntegrationOut(BaseModel):
    connected: bool
    enabled: bool
    token_hint: str | None
    login: str | None
    allowed_repos: list[str]
    status: str
    last_error: str | None
    last_checked_at: datetime | None


class GitHubIntegrationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: SecretStr | None = Field(default=None, min_length=20, max_length=300)
    clear_token: bool = False
    enabled: bool | None = None
    allowed_repos: list[str] | None = Field(default=None, max_length=100)

    @field_validator("allowed_repos")
    @classmethod
    def _repos(cls, value: list[str] | None) -> list[str] | None:
        from app.integrations.github import REPO_RE

        if value is None:
            return None
        cleaned = [v.strip() for v in value if v.strip()]
        for repo in cleaned:
            if not REPO_RE.match(repo):
                raise ValueError(f"'{repo}' is not owner/name")
        return list(dict.fromkeys(cleaned))


class SandboxStatus(BaseModel):
    configured: bool
    ok: bool
    image: str | None
    limits: dict[str, Any]
    network: str
    allowed_commands: list[str]


class IntegrationsStatus(BaseModel):
    sandbox: SandboxStatus
    web_search: bool
    github: GitHubIntegrationOut


class McpServerOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    url: str
    has_token: bool
    enabled: bool
    status: str
    last_error: str | None
    last_checked_at: datetime | None
    server_info: dict[str, Any]
    headers: dict[str, Any] = Field(default_factory=dict)
    auth_source: str = "token"
    tools: list[ToolOut]


class McpServerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    url: str = Field(min_length=8, max_length=500, pattern=r"^https?://")
    token: SecretStr | None = Field(default=None, max_length=2000)


GITHUB_TOOLSETS = (
    "repos",
    "issues",
    "pull_requests",
    "actions",
    "code_security",
    "dependabot",
    "discussions",
    "gists",
    "git",
    "labels",
    "notifications",
    "orgs",
    "projects",
    "security_advisories",
    "stargazers",
    "users",
)


class GitHubMcpCreate(BaseModel):
    """Connect the official GitHub MCP server with the token saved in Integrations → GitHub."""

    model_config = ConfigDict(extra="forbid")

    readonly: bool = True
    toolsets: list[str] = Field(
        default_factory=lambda: ["repos", "issues", "pull_requests"], max_length=20
    )

    @field_validator("toolsets")
    @classmethod
    def _toolsets(cls, value: list[str]) -> list[str]:
        unknown = [t for t in value if t not in GITHUB_TOOLSETS]
        if unknown:
            raise ValueError(f"unknown toolsets: {unknown}")
        return list(dict.fromkeys(value)) or ["repos"]


class McpServerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=64)
    url: str | None = Field(default=None, min_length=8, max_length=500, pattern=r"^https?://")
    token: SecretStr | None = Field(default=None, max_length=2000)
    clear_token: bool = False
    enabled: bool | None = None


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    kind: str
    task_id: uuid.UUID | None
    created_at: datetime
    cleaned_at: datetime | None


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)


class WorkspaceEntry(BaseModel):
    path: str
    type: Literal["file", "dir", "link"]
    size: int
    modified_at: datetime


class WorkspaceFileContent(BaseModel):
    path: str
    size: int
    content: str
    truncated: bool


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    actor_type: str
    actor_id: uuid.UUID | None
    action: str
    outcome: str
    resource_type: str | None
    resource_id: str | None
    details: dict[str, Any]


class AuditPage(BaseModel):
    items: list[AuditOut]
    next_cursor: str | None
