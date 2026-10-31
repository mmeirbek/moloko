from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPrimaryKey


class Conversation(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_last_message", "user_id", "last_message_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    model_config_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_configs.id", ondelete="SET NULL")
    )
    last_message_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Message(UUIDPrimaryKey, Timestamps, Base):
    """A chat message. Assistant messages move streaming → completed | failed | cancelled;
    an error is never stored as a completed message (spec invariant 10)."""

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text, server_default="")
    status: Mapped[str] = mapped_column(String(16))  # streaming | completed | failed | cancelled
    model_config_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_configs.id", ondelete="SET NULL")
    )
    provider_kind: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(128))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(500))
    error_id: Mapped[str | None] = mapped_column(String(64))
    agent_run_id: Mapped[uuid.UUID | None]  # set when the message hands off to agents (Sprint 4)
    completed_at: Mapped[datetime | None]
