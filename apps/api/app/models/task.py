from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPrimaryKey


class Task(UUIDPrimaryKey, Timestamps, Base):
    """User / agent / subtask / review task. Subtasks use ``parent_task_id`` (spec 26.3)."""

    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_user_status", "user_id", "status"),
        Index("ix_tasks_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, server_default="")
    task_type: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(20))
    priority: Mapped[int] = mapped_column(Integer, server_default="0")  # -1 low, 0 normal, 1 high
    deadline: Mapped[datetime | None]
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), index=True
    )
    run_id: Mapped[uuid.UUID | None]
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    attempt: Mapped[int] = mapped_column(Integer, server_default="1")
    retry_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL")
    )
    depends_on: Mapped[list[str]] = mapped_column(server_default=text("'[]'::jsonb"))
    progress: Mapped[int] = mapped_column(Integer, server_default="0")
    result: Mapped[str | None] = mapped_column(Text)
    status_reason: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(500))
    error_id: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(16), server_default="user")
    extra: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
