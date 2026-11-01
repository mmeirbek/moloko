from __future__ import annotations

import uuid

from pydantic import BaseModel


class SearchHitOut(BaseModel):
    source_type: str  # memory | file | attachment
    source_id: uuid.UUID
    title: str
    snippet: str
    score: float
    mode: str  # semantic | words
    agent_id: uuid.UUID | None = None
    workspace_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None


class SearchOut(BaseModel):
    query: str
    hits: list[SearchHitOut]


class SearchStatus(BaseModel):
    chunks: int
    with_vectors: int
    sources: int
