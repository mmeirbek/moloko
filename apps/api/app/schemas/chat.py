from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    model_config_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime


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


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=32_000)
    model_config_id: uuid.UUID | None = None
    # Uploaded first via POST /chats/{id}/attachments; at most CHAT_ATTACHMENTS_PER_MESSAGE.
    attachment_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class CancelResult(BaseModel):
    cancelled: bool
