from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPrimaryKey


class IdempotencyKey(UUIDPrimaryKey, Base):
    """Stored responses for ``Idempotency-Key`` requests that start work (spec 12)."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("user_id", "scope", "key"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    scope: Mapped[str] = mapped_column(String(128))  # METHOD + route template
    key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SystemSetting(UUIDPrimaryKey, Timestamps, Base):
    """Per-user switches such as the global kill switch."""

    __tablename__ = "system_settings"
    __table_args__ = (UniqueConstraint("user_id", "key"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(64))
    value: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
