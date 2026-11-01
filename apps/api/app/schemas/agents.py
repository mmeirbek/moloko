from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from app.agents.state import AgentType, AutonomyLevel
from app.schemas.tasks import RunOut, TaskOut


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    agent_type: str
    specialization: str | None
    model_config_id: uuid.UUID | None
    system_prompt: str
    autonomy_level: str
    allowed_tools: list[str]
    permissions: dict[str, Any]
    status: str
    paused_from: str | None
    current_task_id: uuid.UUID | None
    parent_agent_id: uuid.UUID | None
    run_id: uuid.UUID | None
    depth: int
    limits: dict[str, Any]
    memory_settings: dict[str, Any]
    runtime: str
    config_version: int
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AgentLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_steps: int | None = Field(default=None, ge=1, le=1000)
    run_timeout_seconds: int | None = Field(default=None, ge=10, le=86_400)


class MemorySettings(BaseModel):
    """How much saved memory an agent sees (spec 17). Defaults apply to ``{}``."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    include_shared: bool = True  # shared ``user`` memories about the owner
    # Shared notes of these projects are included too.
    projects: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list, max_length=20
    )
    # At most MEMORY_CONTEXT_MAX_CHARS (checked by the service); None = the global limit.
    max_context_chars: int | None = Field(default=None, ge=200, le=200_000)


class AgentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    agent_type: AgentType = AgentType.AUTONOMOUS
    specialization: str | None = Field(default=None, max_length=64)
    model_config_id: uuid.UUID | None = None
    system_prompt: str = Field(default="", max_length=20_000)
    autonomy_level: AutonomyLevel = AutonomyLevel.SUPERVISED
    allowed_tools: list[str] = Field(default_factory=list, max_length=100)
    limits: AgentLimits = Field(default_factory=AgentLimits)
    memory_settings: MemorySettings = Field(default_factory=MemorySettings)


class AgentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    specialization: str | None = Field(default=None, max_length=64)
    model_config_id: uuid.UUID | None = None
    system_prompt: str | None = Field(default=None, max_length=20_000)
    autonomy_level: AutonomyLevel | None = None
    allowed_tools: list[str] | None = Field(default=None, max_length=100)
    limits: AgentLimits | None = None
    memory_settings: MemorySettings | None = None


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID | None = None  # run an existing (created) task …
    title: str | None = Field(default=None, min_length=1, max_length=200)  # … or a new one
    description: str = Field(default="", max_length=50_000)


class StartedRun(BaseModel):
    task: TaskOut
    run: RunOut
