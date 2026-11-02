from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text, func
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from app.models.base import Base, UUIDPrimaryKey


class Vector(UserDefinedType[list[float]]):
    """pgvector's ``vector`` without a fixed size (the owner may change the embedding
    model). Values are written as text literals and cast in SQL; they are never read back."""

    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        return "vector"


ischema_names["vector"] = Vector  # so Alembic's comparison recognises the column


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{v:.7g}" for v in values) + "]"


class SearchChunk(UUIDPrimaryKey, Base):
    """A piece of a memory, a workspace file, a chat file, a finished task, an agent↔agent
    message or a chat message, for search. Derived data: it is rebuilt from its source
    whenever the source changes (the source stays the truth)."""

    __tablename__ = "search_chunks"
    __table_args__ = (Index("ix_search_chunks_source", "user_id", "source_type", "source_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # memory | file | attachment | task | agent_message | chat_message
    source_type: Mapped[str] = mapped_column(String(16))
    source_id: Mapped[uuid.UUID]
    # memory: its agent (NULL = shared); task: the agent that did it; agent_message: sender
    agent_id: Mapped[uuid.UUID | None]
    peer_agent_id: Mapped[uuid.UUID | None]  # agent_message: the receiver
    run_id: Mapped[uuid.UUID | None]  # task / agent_message: the run (tree)
    source_at: Mapped[datetime | None]  # when the work happened (task: finished)
    # Display fields of work sources: status, role, message type, task id, agent names.
    meta: Mapped[dict[str, Any]] = mapped_column(server_default=sql_text("'{}'::jsonb"))
    memory_type: Mapped[str | None] = mapped_column(String(24))
    project: Mapped[str | None] = mapped_column(String(100))
    workspace_id: Mapped[uuid.UUID | None]  # file: its workspace
    conversation_id: Mapped[uuid.UUID | None]  # attachment: its chat
    title: Mapped[str] = mapped_column(String(300))
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))  # embedding model (NULL = text only)
    embedding: Mapped[Any] = mapped_column(Vector(), nullable=True, deferred=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
