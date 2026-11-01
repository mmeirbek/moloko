from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKey


class AgentMessage(UUIDPrimaryKey, Base):
    """Structured agent↔agent message (spec 14.4). Delivered only inside one run."""

    __tablename__ = "agent_messages"
    __table_args__ = (Index("ix_agent_messages_receiver", "receiver_agent_id", "created_at"),)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    run_id: Mapped[uuid.UUID] = mapped_column(index=True)  # root run
    sender_agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    receiver_agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE")
    )
    task_id: Mapped[uuid.UUID | None]
    message_type: Mapped[str] = mapped_column(String(32))  # task_result | context | error | note
    content: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(String(16))  # delivered | refused
    error: Mapped[str | None] = mapped_column(String(300))
