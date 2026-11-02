from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.tasks import RunOut, TaskOut

ScheduleKind = Literal["once", "hourly", "daily", "weekly", "monthly"]
ScheduleTarget = Literal["orchestrator", "agent"]
Weekday = Annotated[int, Field(ge=1, le=7)]


class RecurrenceIn(BaseModel):
    """When to run, in the schedule's time zone. Which fields count depends on ``kind``:

    * ``once`` — ``run_at`` (a local date-time without offset is read in the schedule's zone);
    * ``hourly`` — every ``interval_hours`` (1, 2, 3, 4, 6, 8, 12) from ``time`` (default 00:00);
    * ``daily`` — ``time``;
    * ``weekly`` — ``weekdays`` (1 = Monday … 7 = Sunday) and ``time``;
    * ``monthly`` — ``day_of_month`` (1-31; shorter months use their last day) and ``time``.
    """

    model_config = ConfigDict(extra="forbid")

    kind: ScheduleKind
    time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    weekdays: list[Weekday] = Field(default_factory=list, max_length=7)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    interval_hours: int | None = Field(default=None, ge=1, le=24)
    run_at: datetime | None = None


class RecurrenceOut(BaseModel):
    kind: ScheduleKind
    time: str | None
    weekdays: list[int]
    day_of_month: int | None
    interval_hours: int | None
    run_at: datetime | None


class ScheduleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=50_000)
    target: ScheduleTarget = "orchestrator"
    agent_id: uuid.UUID | None = None  # required when target = agent
    recurrence: RecurrenceIn
    timezone: str = Field(min_length=1, max_length=64)  # IANA, e.g. Asia/Almaty
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    """Only the fields sent change; ``recurrence`` is replaced as a whole."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=50_000)
    target: ScheduleTarget | None = None
    agent_id: uuid.UUID | None = None
    recurrence: RecurrenceIn | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    enabled: bool | None = None


class ScheduleOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str
    target: ScheduleTarget
    agent_id: uuid.UUID | None
    recurrence: RecurrenceOut
    timezone: str
    enabled: bool
    next_run_at: datetime | None
    # Waiting for a busy agent since (the run starts when it is free, or is skipped).
    busy_since: datetime | None
    last_run_at: datetime | None
    last_task_id: uuid.UUID | None
    last_task_status: str | None
    # started | skipped | failed; why (an error code such as agent_busy, engine_stopped).
    last_outcome: str | None
    last_reason: str | None
    created_at: datetime
    updated_at: datetime


class ScheduleList(BaseModel):
    items: list[ScheduleOut]
    max_schedules: int
    min_interval_minutes: int


class SchedulePreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recurrence: RecurrenceIn
    timezone: str = Field(min_length=1, max_length=64)


class SchedulePreview(BaseModel):
    """The next few runs (UTC) of a rule, exactly as the worker will compute them."""

    next_runs: list[datetime]


class ScheduleStarted(BaseModel):
    schedule: ScheduleOut
    task: TaskOut
    run: RunOut
