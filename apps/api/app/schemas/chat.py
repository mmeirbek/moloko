from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    model_config_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime
    # Set when older messages are condensed into a summary the model gets (the text itself:
    # GET /chats/{id}/summary). NULL = no summary (or summaries are turned off).
    summary_updated_at: datetime | None = None
    summary_messages: int = 0


class ConversationSummaryOut(BaseModel):
    """The rolling summary of a chat's older messages, as the model gets it."""

    summary: str | None
    summary_messages: int
    summary_upto_at: datetime | None
    summary_updated_at: datetime | None


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    model_config_id: uuid.UUID | None = None


class ConversationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    model_config_id: uuid.UUID | None = None


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    content_type: str
    size: int
    kind: str = "text"  # text | image | pdf
    pages: int | None = None
    created_at: datetime


class RecalledSourceOut(BaseModel):
    """An earlier chat, task or memory that recall gave the model for this answer."""

    type: str  # a search source type: memory | attachment | task | conversation | …
    id: uuid.UUID
    title: str
    date: datetime | None = None
    conversation_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    content: str
    status: str
    model_config_id: uuid.UUID | None
    provider_kind: str | None
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: Decimal | None
    error_code: str | None
    error_message: str | None
    error_id: str | None
    agent_run_id: uuid.UUID | None
    created_at: datetime
    completed_at: datetime | None
    attachments: list[AttachmentOut] = Field(default_factory=list)
    recalled_sources: list[RecalledSourceOut] = Field(default_factory=list)

    @field_validator("recalled_sources", mode="before")
    @classmethod
    def _none_is_empty(cls, value: Any) -> Any:
        return [] if value is None else value


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=32_000)
    model_config_id: uuid.UUID | None = None
    # Uploaded first via POST /chats/{id}/attachments; at most CHAT_ATTACHMENTS_PER_MESSAGE.
    attachment_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class CancelResult(BaseModel):
    cancelled: bool
