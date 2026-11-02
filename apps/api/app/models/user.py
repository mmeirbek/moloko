from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, String, Text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPrimaryKey

# Width of users.display_name (also the API's limit for it).
DISPLAY_NAME_MAX_CHARS = 128


class User(UUIDPrimaryKey, Timestamps, Base):
    """Owner account. MVP has one owner, but every owned table carries ``user_id``
    so multi-user support can be added later without reshaping data."""

    __tablename__ = "users"

    # Stored normalised (lower-case); see app.schemas.auth.USERNAME_PATTERN.
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(DISPLAY_NAME_MAX_CHARS))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    last_login_at: Mapped[datetime | None]
    # The owner's own sign-in lifetime; NULL = the configured default (SESSION_TTL_HOURS).
    # Always applied within SESSION_TTL_MIN_HOURS..SESSION_TTL_MAX_HOURS.
    session_ttl_hours: Mapped[int | None]
    # How moloko addresses the owner in every answer ("Мейрбек Максатович"); NULL = no
    # particular form. Stored normalised (one line, at most ADDRESS_AS_MAX_CHARS) — see
    # app.services.addressing.
    address_as: Mapped[str | None] = mapped_column(Text)
