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


class BackupFile(BaseModel):
    name: str
    kind: str
    bytes: int
    at: datetime


class OffsiteAttempt(BaseModel):
    """The last try to send a backup off-site (infrastructure/backup/offsite.sh)."""

    ok: bool
    at: datetime | None = None
    error_code: str | None = None  # no_repository, wrong_password, disk_missing, failed, …
    error: str | None = None  # restic's last message (English, no secrets)


class OffsiteCopy(BaseModel):
    """The last good off-site copy: one restic snapshot of one local backup set."""

    at: datetime
    snapshot: str
    source: str | None = None  # the local dump it holds
    source_at: datetime | None = None
    bytes: int | None = None  # size of the backup set
    added_bytes: int | None = None  # new data uploaded (after deduplication + compression)
    stored_bytes: int | None = None  # the whole repository
    snapshots: int | None = None  # copies kept


class OffsiteCheck(BaseModel):
    """The last `restic check --read-data-subset`."""

    ok: bool
    at: datetime | None = None
    subset: str | None = None
    error_code: str | None = None
    detail: str | None = None


class OffsiteDrill(BaseModel):
    """The last restore drill from the off-site copy into a scratch database."""

    ok: bool
    at: datetime | None = None
    snapshot: str | None = None
    same_as_local: bool | None = None  # the restored dump equals the local one
    error_code: str | None = None
    detail: str | None = None


class OffsiteStatus(BaseModel):
    enabled: bool
    kind: str | None = None  # s3, sftp, rest, disk, …
    repository: str | None = None  # where to (never with credentials)
    keep_daily: int | None = None
    keep_weekly: int | None = None
    keep_monthly: int | None = None
    check_days: int | None = None
    drill_days: int | None = None
    last_attempt: OffsiteAttempt | None = None
    last_copy: OffsiteCopy | None = None
    age_hours: float | None = None  # since the last good copy
    check: OffsiteCheck | None = None
    drill: OffsiteDrill | None = None


class BackupsStatus(BaseModel):
    configured: bool
    last: dict[str, Any] | None
    age_hours: float | None
    drill: dict[str, Any] | None
    files: list[BackupFile]
    same_disk_as_data: bool | None
    offsite: OffsiteStatus


class DiskStatus(BaseModel):
    path: str
    total_bytes: int
    free_bytes: int
    free_percent: float
    low: bool


class StorageStatus(BaseModel):
    backups: BackupsStatus
    disks: list[DiskStatus]
    warnings: list[str]


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
    team: list[Any] = Field(default_factory=list)  # the owner's own agents that took parts
    subtasks: list[TaskOut]
    messages: list[AgentMessageOut]


class HandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=32_000)
