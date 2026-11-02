"""Sprint 7: tools, MCP servers, integrations, workspaces, approvals, tool calls."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPrimaryKey


def _utcnow() -> datetime:
    return datetime.now(UTC)


class McpServer(UUIDPrimaryKey, Timestamps, Base):
    """A registered MCP server (spec 15.5). Its tools start disabled."""

    __tablename__ = "mcp_servers"
    __table_args__ = (UniqueConstraint("user_id", "slug"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(64))
    slug: Mapped[str] = mapped_column(String(24))  # tool-name prefix: mcp_<slug>_<tool>
    url: Mapped[str] = mapped_column(String(500))
    secret_encrypted: Mapped[str | None] = mapped_column(Text)  # optional bearer token
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    status: Mapped[str] = mapped_column(String(16), server_default="unknown")  # ok | error
    last_error: Mapped[str | None] = mapped_column(String(500))
    last_checked_at: Mapped[datetime | None]
    server_info: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    # Non-secret extra request headers (e.g. X-MCP-Readonly for GitHub's server).
    headers: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    # Where the bearer token comes from: "token" (stored here) or "github" (the GitHub
    # integration's token, so it is entered once).
    auth_source: Mapped[str] = mapped_column(String(16), server_default="token")


class Tool(UUIDPrimaryKey, Timestamps, Base):
    """Tool registry entry (spec 15.1). Built-in tools are defined in code; this row keeps
    the owner's switches. MCP tools live only here."""

    __tablename__ = "tools"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16))  # builtin | mcp
    server_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mcp_servers.id", ondelete="CASCADE")
    )
    remote_name: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, server_default="")
    category: Mapped[str | None] = mapped_column(String(16))  # read | write | sensitive
    input_schema: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="false")
    available: Mapped[bool] = mapped_column(Boolean, server_default="true")


class Integration(UUIDPrimaryKey, Timestamps, Base):
    """GitHub and other integration settings; secrets encrypted at rest."""

    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("user_id", "kind"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))  # github
    config: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    secret_encrypted: Mapped[str | None] = mapped_column(Text)
    secret_hint: Mapped[str | None] = mapped_column(String(16))  # "…last4"
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    status: Mapped[str] = mapped_column(String(16), server_default="unknown")
    last_error: Mapped[str | None] = mapped_column(String(500))
    last_checked_at: Mapped[datetime | None]


class Workspace(UUIDPrimaryKey, Timestamps, Base):
    """A sandbox working directory (spec 16): one per root task, or a named project."""

    __tablename__ = "workspaces"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(16))  # task | project
    task_id: Mapped[uuid.UUID | None] = mapped_column(index=True)  # root task (kind=task)
    cleaned_at: Mapped[datetime | None]  # files removed by the clean-up job


class WorkspaceFile(UUIDPrimaryKey, Base):
    """Metadata of a file an agent created or changed (content stays on disk)."""

    __tablename__ = "workspace_files"
    __table_args__ = (UniqueConstraint("workspace_id", "path"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(String(1024))
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    deleted: Mapped[bool] = mapped_column(Boolean, server_default="false")
    last_task_id: Mapped[uuid.UUID | None]
    last_agent_id: Mapped[uuid.UUID | None]
    last_tool_call_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        default=_utcnow, onupdate=_utcnow, server_default=text("now()")
    )


class ToolCall(UUIDPrimaryKey, Timestamps, Base):
    """One tool call by an agent: decision, approval, outcome (spec 15.2, 16).

    The row is the source of truth for the call's result, so a resumed run never
    executes the same call twice.
    """

    __tablename__ = "tool_calls"
    __table_args__ = (
        UniqueConstraint("run_id", "call_id"),
        Index("ix_tool_calls_task", "task_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"))
    task_id: Mapped[uuid.UUID]
    agent_id: Mapped[uuid.UUID]
    call_id: Mapped[str] = mapped_column(String(128))  # the model's id for the call
    step: Mapped[int] = mapped_column(Integer)
    tool_name: Mapped[str] = mapped_column(String(64))
    category: Mapped[str | None] = mapped_column(String(16))
    args: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    args_hash: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str | None] = mapped_column(String(20))  # allow | require_approval | deny
    decision_reason: Mapped[str | None] = mapped_column(String(500))
    approval_id: Mapped[uuid.UUID | None]
    # pending | awaiting_approval | running | succeeded | failed | denied | rejected
    # | expired | unknown
    status: Mapped[str] = mapped_column(String(20))
    result: Mapped[str | None] = mapped_column(Text)
    is_error: Mapped[bool] = mapped_column(Boolean, server_default="false")
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class Approval(UUIDPrimaryKey, Timestamps, Base):
    """Approval of ONE operation: tool + hash of the exact arguments + expiry (spec 15.4)."""

    __tablename__ = "approvals"
    __table_args__ = (Index("ix_approvals_user_status", "user_id", "status"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    agent_id: Mapped[uuid.UUID]
    task_id: Mapped[uuid.UUID] = mapped_column(index=True)
    run_id: Mapped[uuid.UUID]
    tool_call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tool_calls.id", ondelete="CASCADE"))
    tool_name: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(16))
    args: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    args_hash: Mapped[str] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(String(500))
    resources: Mapped[list[str]] = mapped_column(server_default=text("'[]'::jsonb"))
    consequences: Mapped[str] = mapped_column(Text, server_default="")
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16))  # pending|approved|rejected|expired|cancelled
    expires_at: Mapped[datetime]
    resolved_at: Mapped[datetime | None]
    used_at: Mapped[datetime | None]


class PushSubscription(UUIDPrimaryKey, Timestamps, Base):
    """A device that receives Web Push notifications while moloko is closed."""

    __tablename__ = "push_subscriptions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    endpoint: Mapped[str] = mapped_column(String(1000), unique=True)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    kinds: Mapped[list[str]] = mapped_column(server_default=text("'[]'::jsonb"))
    locale: Mapped[str] = mapped_column(String(8), server_default="ru")
    label: Mapped[str] = mapped_column(String(200), server_default="")
    failures: Mapped[int] = mapped_column(Integer, server_default="0")
    last_sent_at: Mapped[datetime | None]
