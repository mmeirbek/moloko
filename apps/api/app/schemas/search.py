from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class SearchHitOut(BaseModel):
    # memory | file | attachment | task | agent_message | chat_message
    source_type: str
    source_id: uuid.UUID
    title: str
    snippet: str
    score: float
    mode: str  # semantic | words
    agent_id: uuid.UUID | None = None  # memory: its agent; task: who did it; message: sender
    workspace_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    # Work history (task / agent_message / chat_message)
    peer_agent_id: uuid.UUID | None = None  # agent_message: the receiver
    run_id: uuid.UUID | None = None
    source_at: datetime | None = None  # when the work happened
    status: str | None = None  # task: completed | failed | cancelled
    role: str | None = None  # chat_message: user | assistant
    message_type: str | None = None  # agent_message: note | request | task_result | …
    task_id: uuid.UUID | None = None  # agent_message: the task it belongs to
    agent_name: str | None = None
    peer_agent_name: str | None = None


class SearchOut(BaseModel):
    query: str
    hits: list[SearchHitOut]


class SearchStatus(BaseModel):
    chunks: int
    with_vectors: int
    sources: int
