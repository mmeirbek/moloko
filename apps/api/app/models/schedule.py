from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPrimaryKey


class Schedule(UUIDPrimaryKey, Timestamps, Base):
    """A task the owner wants started on a schedule (owner request, see docs/decisions.md).

    The rule (kind + fields) is local wall-clock time in ``timezone``; ``next_run_at`` is
    the computed UTC moment the worker starts it next (NULL = nothing planned: switched off,
    or a one-off that already ran).
    """

    __tablename__ = "schedules"
    __table_args__ = (
        Index("ix_schedules_due", "enabled", "next_run_at"),
        Index("ix_schedules_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, server_default="")
    target: Mapped[str] = mapped_column(String(16))  # orchestrator | agent
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), index=True
    )
    # Rule (app/schedules/recurrence.py): once | hourly | daily | weekly | monthly
    kind: Mapped[str] = mapped_column(String(16))
    at_time: Mapped[str | None] = mapped_column(String(5))  # "HH:MM", local
    weekdays: Mapped[list[int]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    day_of_month: Mapped[int | None] = mapped_column(SmallInteger)
    interval_hours: Mapped[int | None] = mapped_column(SmallInteger)
    run_at: Mapped[datetime | None]  # once
    timezone: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    next_run_at: Mapped[datetime | None]
    # Waiting for a busy agent since (cleared when the run starts or is skipped).
    busy_since: Mapped[datetime | None]
    # The last occurrence: when, which task, and how it went (started | skipped | failed + why).
    last_run_at: Mapped[datetime | None]
    last_task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL")
    )
    last_outcome: Mapped[str | None] = mapped_column(String(16))
    last_reason: Mapped[str | None] = mapped_column(String(64))
