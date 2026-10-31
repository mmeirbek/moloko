from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey
from app.models.user import User


class Session(UUIDPrimaryKey, Timestamps, Base):
    """Server-side auth session. The cookie holds a random token; only its SHA-256
    hash is stored here."""

    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    last_seen_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))

    user: Mapped[User] = relationship(lazy="joined")
