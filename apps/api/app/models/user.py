from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, String, true
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPrimaryKey


class User(UUIDPrimaryKey, Timestamps, Base):
    """Owner account. MVP has one owner, but every owned table carries ``user_id``
    so multi-user support can be added later without reshaping data."""

    __tablename__ = "users"

    # Stored normalised (lower-case); see app.schemas.auth.USERNAME_PATTERN.
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    last_login_at: Mapped[datetime | None]
