from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKey


class AuditLog(UUIDPrimaryKey, Base):
    """Append-only security/audit journal (spec section 20).

    Immutability is enforced in the database: a trigger rejects UPDATE and DELETE
    (see the initial migration). There is intentionally no foreign key to ``users``
    so audit history survives any future account deletion.
    """

    __tablename__ = "audit_logs"

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    actor_type: Mapped[str] = mapped_column(String(32))  # user | agent | system | anonymous
    actor_id: Mapped[uuid.UUID | None]
    user_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    action: Mapped[str] = mapped_column(String(64))  # e.g. auth.login_failed
    outcome: Mapped[str] = mapped_column(String(16))  # success | failure | denied
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(128))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))

    __table_args__ = (Index("ix_audit_logs_action_created_at", "action", "created_at"),)
