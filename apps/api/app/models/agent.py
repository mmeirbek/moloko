from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPrimaryKey


class Agent(UUIDPrimaryKey, Timestamps, Base):
    """Agent profile (spec 8.3). Orchestrator, temporary subagent or persistent autonomous agent."""

    __tablename__ = "agents"
    __table_args__ = (Index("ix_agents_user_type", "user_id", "agent_type"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, server_default="")
    agent_type: Mapped[str] = mapped_column(String(16))
    specialization: Mapped[str | None] = mapped_column(String(64))
    # provider + model are chosen through a model config (spec: model per agent).
    model_config_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_configs.id", ondelete="SET NULL")
    )
    system_prompt: Mapped[str] = mapped_column(Text, server_default="")
    autonomy_level: Mapped[str] = mapped_column(String(16), server_default="supervised")
    allowed_tools: Mapped[list[str]] = mapped_column(server_default=text("'[]'::jsonb"))
    permissions: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(String(16), server_default="idle")
    paused_from: Mapped[str | None] = mapped_column(String(16))
    current_task_id: Mapped[uuid.UUID | None]
    parent_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL")
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(index=True)  # subagents: the run they serve
    depth: Mapped[int] = mapped_column(Integer, server_default="0")
    limits: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    memory_settings: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    runtime: Mapped[str] = mapped_column(String(32), server_default="native")
    # A project workspace shared by this agent's tasks; NULL = a new workspace per task.
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL")
    )
    config_version: Mapped[int] = mapped_column(Integer, server_default="1")
    archived_at: Mapped[datetime | None]
    # Monthly limit in USD for this agent's model calls (its subagents included);
    # NULL = no limit of its own (the global budget still applies).
    monthly_budget_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    # Who this persistent agent may talk to directly (agent_ask / agent_tell):
    # {} = everyone (default), {"mode": "list", "agent_ids": [...]}, {"mode": "none"}.
    # Both sides must allow it. Subagents only talk to their siblings (same run tree).
    contacts: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    # «Полный доступ» (owner's decision, docs/decisions.md): since when this persistent agent
    # may use every enabled, available tool without approvals; NULL = off. Set only through
    # PUT /agents/{id}/full-access (password), never copied to subagents or templates.
    full_access_since: Mapped[datetime | None]
    # Its face and office character: one of app/agents/looks.py ANIMALS (owner's choice or
    # random); NULL for the Orchestrator (the moloko cow).
    animal: Mapped[str | None] = mapped_column(String(40))

    @property
    def full_access(self) -> bool:
        """Only a persistent autonomous agent can have it (never subagents/the Orchestrator)."""
        return self.full_access_since is not None and self.agent_type == "autonomous"


class SavedAgentTemplate(UUIDPrimaryKey, Timestamps, Base):
    """The owner's own agent template ("Save as template"): an agent's reusable
    configuration. Memory, history and the project workspace are not part of it."""

    __tablename__ = "agent_templates"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, server_default="")
    specialization: Mapped[str | None] = mapped_column(String(64))
    model_config_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_configs.id", ondelete="SET NULL")
    )
    system_prompt: Mapped[str] = mapped_column(Text, server_default="")
    autonomy_level: Mapped[str] = mapped_column(String(16), server_default="supervised")
    allowed_tools: Mapped[list[str]] = mapped_column(server_default=text("'[]'::jsonb"))
    permissions: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    limits: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    memory_settings: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    monthly_budget_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    # The agent it was saved from (provenance only; the template does not follow it).
    source_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL")
    )


class AgentRun(UUIDPrimaryKey, Timestamps, Base):
    """One execution of an agent for a goal. ``state`` is the resumable checkpoint."""

    __tablename__ = "agent_runs"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[uuid.UUID] = mapped_column(index=True)
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(20))
    phase: Mapped[str | None] = mapped_column(String(20))
    plan: Mapped[dict[str, Any] | None]
    state: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    steps: Mapped[int] = mapped_column(Integer, server_default="0")
    usage: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    result: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(500))
    error_id: Mapped[str | None] = mapped_column(String(64))
    conversation_id: Mapped[uuid.UUID | None]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
