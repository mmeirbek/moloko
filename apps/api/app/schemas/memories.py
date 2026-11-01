from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.agents.state import MemoryType


class MemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID | None
    memory_type: str
    project: str | None
    title: str
    content: str
    pinned: bool
    revision: int
    created_by: str
    created_at: datetime
    updated_at: datetime


class MemoryCreate(BaseModel):
    """``user`` = shared facts about the owner (no agent); ``project`` needs a project name;
    ``agent`` / ``task_context`` / ``conversation_context`` belong to one agent."""

    model_config = ConfigDict(extra="forbid")

    memory_type: MemoryType
    agent_id: uuid.UUID | None = None
    project: str | None = Field(default=None, min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    # The length limit is MEMORY_ENTRY_MAX_CHARS (checked by the service).
    content: str = Field(min_length=1, max_length=100_000)
    pinned: bool = False


class MemoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1, max_length=100_000)
    project: str | None = Field(default=None, min_length=1, max_length=100)
    pinned: bool | None = None


class MemoryRevisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    revision: int
    memory_type: str
    agent_id: uuid.UUID | None
    project: str | None
    title: str
    content: str
    pinned: bool
    changed_by: str
    created_at: datetime


class MemoryContextOut(BaseModel):
    """Exactly what an agent's prompt receives from memory, and how much of the budget."""

    enabled: bool
    text: str
    included: list[uuid.UUID]
    omitted: list[uuid.UUID]
    chars: int
    max_chars: int
