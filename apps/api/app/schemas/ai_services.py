from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class AiServicesOut(BaseModel):
    provider_id: uuid.UUID | None  # the chosen provider (None = automatic)
    active_provider_id: uuid.UUID | None  # what is used right now
    active_provider_name: str | None
    available: bool
    transcription_model: str
    embedding_model: str
    embedding_dimensions: int
    semantic_search: bool


class AiServicesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: uuid.UUID | None = None
    transcription_model: str | None = Field(default=None, max_length=128)
    embedding_model: str | None = Field(default=None, max_length=128)
    embedding_dimensions: int | None = Field(default=None, ge=64, le=4096)
    semantic_search: bool = True


class Transcript(BaseModel):
    text: str
