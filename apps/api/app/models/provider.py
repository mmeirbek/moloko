from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey


class Provider(UUIDPrimaryKey, Timestamps, Base):
    """A configured AI provider account (spec 8.1 ``model_providers``).

    Credentials are encrypted at rest; only a short hint is ever shown to the UI.
    """

    __tablename__ = "model_providers"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))  # openai | anthropic | mock
    name: Mapped[str] = mapped_column(String(64))
    base_url: Mapped[str | None] = mapped_column(String(512))
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    api_key_hint: Mapped[str | None] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=true())

    models: Mapped[list[ModelConfig]] = relationship(
        back_populates="provider", cascade="all, delete-orphan", passive_deletes=True
    )


class ModelConfig(UUIDPrimaryKey, Timestamps, Base):
    """A model the owner can pick (spec 8.1 ``model_configs``). Names come from the
    provider's model list or are typed in by the owner — never hardcoded."""

    __tablename__ = "model_configs"
    __table_args__ = (UniqueConstraint("provider_id", "model"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_providers.id", ondelete="CASCADE"), index=True
    )
    model: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str | None] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=true())
    is_default: Mapped[bool] = mapped_column(Boolean, server_default=false())
    # Optional owner-entered prices (USD per million tokens) for approximate cost tracking.
    input_price_per_mtok: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    output_price_per_mtok: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    params: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))

    provider: Mapped[Provider] = relationship(back_populates="models", lazy="joined")
