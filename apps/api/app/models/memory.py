from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPrimaryKey


class Memory(UUIDPrimaryKey, Timestamps, Base):
    """A structured memory record (spec 17). Plain rows, no vectors.

    ``agent_id`` NULL = shared (``user`` facts, ``project`` notes). Memory is always put
    into prompts fenced as data, never as instructions.
    """

    __tablename__ = "memories"
    __table_args__ = (Index("ix_memories_user_agent", "user_id", "agent_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    memory_type: Mapped[str] = mapped_column(String(24))
    project: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    pinned: Mapped[bool] = mapped_column(Boolean, server_default="false")
    revision: Mapped[int] = mapped_column(Integer, server_default="1")
    created_by: Mapped[str] = mapped_column(String(16))  # user | agent | system


class MemoryRevision(UUIDPrimaryKey, Base):
    """Change history: one row per saved version of a memory (spec 17)."""

    __tablename__ = "memory_revisions"
    __table_args__ = (UniqueConstraint("memory_id", "revision"),)

    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), server_default=func.now()
    )
    # The (memory_id, revision) unique constraint also serves lookups by memory.
    memory_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("memories.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    revision: Mapped[int] = mapped_column(Integer)
    memory_type: Mapped[str] = mapped_column(String(24))
    agent_id: Mapped[uuid.UUID | None]
    project: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    pinned: Mapped[bool] = mapped_column(Boolean)
    changed_by: Mapped[str] = mapped_column(String(16))
