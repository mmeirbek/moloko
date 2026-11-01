from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKey


class UsageRecord(UUIDPrimaryKey, Base):
    """One model call: who used which model, how many tokens, and the approximate cost
    (from the owner's prices; NULL when the model has no prices). Append-only ledger
    behind Settings → Costs and the monthly budget."""

    __tablename__ = "usage_records"
    __table_args__ = (Index("ix_usage_records_user_created", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(16))  # chat | agent | orchestrator
    agent_id: Mapped[uuid.UUID | None]
    agent_name: Mapped[str | None] = mapped_column(String(100))  # snapshot for history
    task_id: Mapped[uuid.UUID | None]
    run_id: Mapped[uuid.UUID | None]
    conversation_id: Mapped[uuid.UUID | None]
    model_config_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_configs.id", ondelete="SET NULL")
    )
    provider_kind: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    input_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
