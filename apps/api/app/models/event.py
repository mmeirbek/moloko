from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Identity, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKey


class AgentEvent(UUIDPrimaryKey, Base):
    """Append-only event log (spec 10): the audit history and the realtime feed.

    ``seq`` is a monotonically increasing identity used for resume. Writers take a
    transaction-level advisory lock before inserting (app/events/bus.py), so events
    become visible in ``seq`` order — a client resuming "after seq N" never misses one.
    """

    __tablename__ = "agent_events"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 — fetch seq on INSERT
    __table_args__ = (
        Index("ix_agent_events_run_seq", "run_id", "seq"),
        Index("ix_agent_events_task_seq", "task_id", "seq"),
        Index("ix_agent_events_user_seq", "user_id", "seq"),
    )

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    type: Mapped[str] = mapped_column(String(48))
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    user_id: Mapped[uuid.UUID]
    agent_id: Mapped[uuid.UUID | None]
    task_id: Mapped[uuid.UUID | None]
    run_id: Mapped[uuid.UUID | None]
    payload: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
