from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    task_id: uuid.UUID
    parent_run_id: uuid.UUID | None
    status: str
    phase: str | None
    plan: dict[str, Any] | None
    steps: int
    usage: dict[str, Any]
    result: str | None
    error_code: str | None
    error_message: str | None
    error_id: str | None
    conversation_id: uuid.UUID | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str
    task_type: str
    status: str
    priority: int
    deadline: datetime | None
    agent_id: uuid.UUID | None
    run_id: uuid.UUID | None
    parent_task_id: uuid.UUID | None
    attempt: int
    retry_of_id: uuid.UUID | None
    depends_on: list[str]
    progress: int
    result: str | None
    status_reason: str | None
    error_code: str | None
    error_message: str | None
    error_id: str | None
    created_by: str
    extra: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=50_000)
    agent_id: uuid.UUID | None = None
    priority: int = Field(default=0, ge=-1, le=1)
    deadline: datetime | None = None
    start: bool = True  # start right away when an agent is assigned


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=50_000)
    agent_id: uuid.UUID | None = None
    priority: int | None = Field(default=None, ge=-1, le=1)
    deadline: datetime | None = None


TaskFilter = Literal["all", "active", "completed", "failed", "cancelled"]


class EventOut(BaseModel):
    id: uuid.UUID
    seq: int
    type: str
    version: int
    timestamp: datetime
    agent_id: uuid.UUID | None
    task_id: uuid.UUID | None
    run_id: uuid.UUID | None
    payload: dict[str, Any]


class TaskDetail(BaseModel):
    task: TaskOut
    subtasks: list[TaskOut]
    run: RunOut | None = None


class SystemLimits(BaseModel):
    max_steps_per_run: int
    run_timeout_seconds: int
    max_active_subagents_per_run: int
    max_subagent_depth: int
    memory_context_max_chars: int
    memory_entry_max_chars: int


class SystemState(BaseModel):
    engine_stopped: bool
    active_tasks: int


class StopAllResult(BaseModel):
    cancelled_tasks: int


class AgentMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    run_id: uuid.UUID
    sender_agent_id: uuid.UUID
    receiver_agent_id: uuid.UUID
    task_id: uuid.UUID | None
    message_type: str
    content: dict[str, Any]
    status: str


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=50_000)


class RunTree(BaseModel):
    run: RunOut
    task: TaskOut
    subagents: list[Any]  # AgentOut
    subtasks: list[TaskOut]
    messages: list[AgentMessageOut]


class HandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=32_000)
