"""Keeps `search_chunks` in step with its sources (worker job, every few seconds).

Sources: memories, text files in workspaces, and text/PDF files sent in chats — and the
work history (owner request: agents can always check what was done): finished tasks of all
agents (subagents and the Orchestrator included), delivered agent↔agent messages and
completed chat messages. Each source is split into chunks; when semantic search is on and
an OpenAI-type provider exists, the chunks also get embeddings (pgvector). Without one,
chunks are still stored and found by words. Only changed sources are re-indexed (content
hash), deleted ones are removed (a deleted chat leaves the search with its messages).

Work sources are many and only grow, so a pass reads just their ids and a cheap version
(status + last change) and loads the text of at most ``WORK_INDEX_BATCH`` changed ones,
newest first — a backfill of a long history goes a pass at a time and never stalls the
worker. Each takes at most ``WORK_INDEX_MAX_CHUNKS`` chunks.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.agents.state import TERMINAL_TASK
from app.core.config import Settings
from app.models.agent import Agent
from app.models.agent_message import AgentMessage
from app.models.chat import Attachment, Conversation, Message
from app.models.memory import Memory
from app.models.search import SearchChunk, vector_literal
from app.models.task import Task
from app.models.tooling import WorkspaceFile
from app.models.user import User
from app.providers.gateway import ModelGateway
from app.services import ai_services

logger = logging.getLogger("moloko.search")

TEXT_FILE_MAX_BYTES = 300_000
MAX_CHUNKS_PER_SOURCE = 200


@dataclass(frozen=True)
class Source:
    type: str
    id: uuid.UUID
    title: str
    text: str
    hash: str
    agent_id: uuid.UUID | None = None
    memory_type: str | None = None
    project: str | None = None
    workspace_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    peer_agent_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    source_at: datetime | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    max_chunks: int | None = None  # None = MAX_CHUNKS_PER_SOURCE


WORK_TYPES = ("task", "agent_message", "chat_message")
# Bump when the indexed text of work sources changes shape: everything is re-indexed.
WORK_FORMAT = "work-v1"
Versions = dict[tuple[str, uuid.UUID], tuple[str, datetime | None]]  # key -> (hash, date)


def chunk_text(body: str, size: int) -> list[str]:
    """Paragraph-aware chunks of at most `size` characters (long paragraphs are cut). Pure."""
    chunks: list[str] = []
    current = ""
    for para in [p.strip() for p in body.replace("\r\n", "\n").split("\n\n")]:
        if not para:
            continue
        while len(para) > size:
            if current:
                chunks.append(current)
                current = ""
            cut = para.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            chunks.append(para[:cut].strip())
            para = para[cut:].strip()
        if current and len(current) + 2 + len(para) > size:
            chunks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks[:MAX_CHUNKS_PER_SOURCE]


def _hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


async def sources_for(db: AsyncSession, settings: Settings, user_id: uuid.UUID) -> list[Source]:
    from app.services.workspaces import workspace_dir

    out: list[Source] = []
    for m in (await db.execute(select(Memory).where(Memory.user_id == user_id))).scalars():
        out.append(
            Source(
                "memory",
                m.id,
                m.title,
                f"{m.title}\n\n{m.content}",
                _hash(m.title, m.content),
                agent_id=m.agent_id,
                memory_type=m.memory_type,
                project=m.project,
            )
        )
    # Only the start of a big file is indexed (MAX_CHUNKS_PER_SOURCE chunks anyway).
    head = func.left(Attachment.text, MAX_CHUNKS_PER_SOURCE * settings.search_chunk_chars)
    attachments = await db.execute(
        select(
            Attachment.id, Attachment.filename, head, Attachment.sha256, Attachment.conversation_id
        ).where(
            Attachment.user_id == user_id,
            Attachment.message_id.is_not(None),
            Attachment.kind.in_(("text", "pdf")),
        )
    )
    for a_id, filename, body, sha, conversation_id in attachments:
        if body and body.strip():
            out.append(
                Source("attachment", a_id, filename, body, sha, conversation_id=conversation_id)
            )
    from app.models.tooling import Workspace

    files = await db.execute(
        select(WorkspaceFile)
        .join(Workspace, Workspace.id == WorkspaceFile.workspace_id)
        .where(
            Workspace.user_id == user_id,
            WorkspaceFile.deleted.is_(False),
            WorkspaceFile.size <= TEXT_FILE_MAX_BYTES,
            Workspace.cleaned_at.is_(None),
        )
    )
    for f in files.scalars():
        if not f.sha256:
            continue
        path = workspace_dir(settings, f.workspace_id) / f.path
        try:
            data = path.read_bytes() if path.is_file() and not path.is_symlink() else b""
            body = data.decode("utf-8") if b"\x00" not in data else ""
        except (OSError, UnicodeDecodeError):
            body = ""
        if body.strip():
            out.append(Source("file", f.id, f.path, body, f.sha256, workspace_id=f.workspace_id))
    return out


# --- work history ------------------------------------------------------------------------


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value else ""


async def work_versions(db: AsyncSession, user_id: uuid.UUID) -> Versions:
    """Every work source of one owner: its version hash and date. Cheap columns only."""
    out: Versions = {}
    tasks = await db.execute(
        select(Task.id, Task.status, Task.updated_at, Task.completed_at).where(
            Task.user_id == user_id, Task.status.in_([s.value for s in TERMINAL_TASK])
        )
    )
    for task_id, status, updated, completed in tasks.all():
        out[("task", task_id)] = (_hash(WORK_FORMAT, status, _iso(updated)), completed or updated)
    messages = await db.execute(
        select(AgentMessage.id, AgentMessage.created_at).where(
            AgentMessage.user_id == user_id, AgentMessage.status == "delivered"
        )
    )
    for message_id, created in messages.all():
        out[("agent_message", message_id)] = (_hash(WORK_FORMAT, "delivered"), created)
    chats = await db.execute(
        select(Message.id, Message.updated_at, Message.created_at, Conversation.title)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Message.user_id == user_id,
            Message.status == "completed",
            Message.role.in_(("user", "assistant")),
            func.trim(Message.content) != "",  # blank: no chunk, would be retried forever
        )
    )
    for message_id, updated, created, title in chats.all():
        out[("chat_message", message_id)] = (_hash(WORK_FORMAT, _iso(updated), title), created)
    return out


def _task_text(task: Task, agent_name: str | None) -> str:
    when = task.completed_at or task.updated_at
    day = when.date().isoformat() if when else ""
    lines = [task.title, " · ".join(p for p in (agent_name or "", task.status, day) if p)]
    if task.description.strip():
        lines.append("Request:\n" + task.description.strip())
    if (task.result or "").strip():
        lines.append("Result:\n" + (task.result or "").strip())
    if task.error_code or task.error_message:
        lines.append(f"Error: {task.error_code or ''} {task.error_message or ''}".strip())
    return "\n\n".join(lines)


async def _task_sources(
    db: AsyncSession, user_id: uuid.UUID, ids: list[uuid.UUID], versions: Versions, cap: int
) -> list[Source]:
    rows = await db.execute(
        select(Task, Agent.name, Agent.agent_type)
        .outerjoin(Agent, Agent.id == Task.agent_id)
        .where(Task.user_id == user_id, Task.id.in_(ids))
    )
    out = []
    for task, name, agent_type in rows.all():
        version = versions.get(("task", task.id))
        if version is None:
            continue
        out.append(
            Source(
                "task",
                task.id,
                task.title,
                _task_text(task, name),
                version[0],
                agent_id=task.agent_id,
                run_id=task.run_id,
                source_at=version[1],
                meta={
                    "status": task.status,
                    "task_type": task.task_type,
                    "agent_name": name,
                    "agent_type": agent_type,
                    "parent_task_id": str(task.parent_task_id) if task.parent_task_id else None,
                },
                max_chunks=cap,
            )
        )
    return out


async def _agent_message_sources(
    db: AsyncSession, user_id: uuid.UUID, ids: list[uuid.UUID], versions: Versions, cap: int
) -> list[Source]:
    sender, receiver = aliased(Agent), aliased(Agent)
    rows = await db.execute(
        select(AgentMessage, sender.name, receiver.name)
        .outerjoin(sender, sender.id == AgentMessage.sender_agent_id)
        .outerjoin(receiver, receiver.id == AgentMessage.receiver_agent_id)
        .where(AgentMessage.user_id == user_id, AgentMessage.id.in_(ids))
    )
    out = []
    for m, from_name, to_name in rows.all():
        version = versions.get(("agent_message", m.id))
        if version is None:
            continue
        content = m.content or {}
        summary = str(content.get("summary") or "")
        who = f"{from_name or '?'} → {to_name or '?'}"
        body = [f"{who} ({m.message_type})", summary, str(content.get("result") or "")]
        body.extend(str(n) for n in content.get("notes") or [])
        out.append(
            Source(
                "agent_message",
                m.id,
                f"{who}: {summary}" if summary else who,
                "\n\n".join(p for p in body if p.strip()),
                version[0],
                agent_id=m.sender_agent_id,
                peer_agent_id=m.receiver_agent_id,
                run_id=m.run_id,
                source_at=version[1],
                meta={
                    "message_type": m.message_type,
                    "agent_name": from_name,
                    "peer_agent_name": to_name,
                    "task_id": str(m.task_id) if m.task_id else None,
                },
                max_chunks=cap,
            )
        )
    return out


async def _chat_message_sources(
    db: AsyncSession, user_id: uuid.UUID, ids: list[uuid.UUID], versions: Versions, cap: int
) -> list[Source]:
    rows = await db.execute(
        select(Message, Conversation.title)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Message.user_id == user_id, Message.id.in_(ids))
    )
    out = []
    for m, title in rows.all():
        version = versions.get(("chat_message", m.id))
        if version is None:
            continue
        out.append(
            Source(
                "chat_message",
                m.id,
                title,
                m.content,
                version[0],
                conversation_id=m.conversation_id,
                run_id=m.agent_run_id,
                source_at=version[1],
                meta={"role": m.role},
                max_chunks=cap,
            )
        )
    return out


async def load_work_sources(
    db: AsyncSession,
    settings: Settings,
    user_id: uuid.UUID,
    keys: list[tuple[str, uuid.UUID]],
    versions: Versions,
) -> list[Source]:
    """The full text of the given work sources (only these are read)."""
    cap = settings.work_index_max_chunks
    ids = {kind: [i for k, i in keys if k == kind] for kind in WORK_TYPES}
    out: list[Source] = []
    if ids["task"]:
        out += await _task_sources(db, user_id, ids["task"], versions, cap)
    if ids["agent_message"]:
        out += await _agent_message_sources(db, user_id, ids["agent_message"], versions, cap)
    if ids["chat_message"]:
        out += await _chat_message_sources(db, user_id, ids["chat_message"], versions, cap)
    return out


async def index_user(
    db: AsyncSession, gateway: ModelGateway, settings: Settings, user_id: uuid.UUID
) -> int:
    """One pass for one owner. Returns how many sources were (re)indexed."""
    try:
        target = await ai_services.resolve(db, gateway, settings, user_id)
        semantic = target.semantic_search
    except ai_services.AiServiceUnavailable:
        target, semantic = None, False
    model = target.embedding_model if (target and semantic) else None

    wanted = {(s.type, s.id): s for s in await sources_for(db, settings, user_id)}
    work = await work_versions(db, user_id)
    indexed = {
        (t, i): (h, m)
        for t, i, h, m in (
            await db.execute(
                select(
                    SearchChunk.source_type,
                    SearchChunk.source_id,
                    SearchChunk.content_hash,
                    SearchChunk.model,
                ).where(SearchChunk.user_id == user_id, SearchChunk.chunk_index == 0)
            )
        ).all()
    }
    gone = [key for key in indexed if key not in wanted and key not in work]
    for source_type, source_id in gone:
        await db.execute(
            delete(SearchChunk).where(
                SearchChunk.user_id == user_id,
                SearchChunk.source_type == source_type,
                SearchChunk.source_id == source_id,
            )
        )
    stale = [
        s for key, s in wanted.items() if key not in indexed or indexed[key] != (s.hash, model)
    ][: settings.search_index_batch]
    changed = [key for key, (h, _) in work.items() if indexed.get(key) != (h, model)]
    changed.sort(key=lambda key: _iso(work[key][1]), reverse=True)  # newest first
    stale += await load_work_sources(
        db, settings, user_id, changed[: settings.work_index_batch], work
    )

    client = ai_services.adapter(gateway, target) if (target and model) else None
    done = 0
    try:
        for source in stale:
            pieces = chunk_text(source.text, settings.search_chunk_chars)[: source.max_chunks]
            vectors: list[list[float]] = []
            if client is not None and target is not None and pieces:
                try:
                    vectors, used = await client.embed(
                        pieces, target.embedding_model, target.embedding_dimensions
                    )
                    db.add(
                        ai_services.ledger_row(
                            user_id, target, "search", target.embedding_model, used
                        )
                    )
                except Exception as exc:  # noqa: BLE001 — keep the text index; retry embeddings later
                    logger.warning("search_embed_failed", extra={"error": type(exc).__name__})
                    vectors = []
            await db.execute(
                delete(SearchChunk).where(
                    SearchChunk.user_id == user_id,
                    SearchChunk.source_type == source.type,
                    SearchChunk.source_id == source.id,
                )
            )
            for i, piece in enumerate(pieces):
                chunk = SearchChunk(
                    user_id=user_id,
                    source_type=source.type,
                    source_id=source.id,
                    agent_id=source.agent_id,
                    memory_type=source.memory_type,
                    project=source.project,
                    workspace_id=source.workspace_id,
                    conversation_id=source.conversation_id,
                    peer_agent_id=source.peer_agent_id,
                    run_id=source.run_id,
                    source_at=source.source_at,
                    meta={k: v for k, v in source.meta.items() if v is not None},
                    title=(" ".join(source.title.split()) or "—")[:300],
                    chunk_index=i,
                    text=piece,
                    content_hash=source.hash,
                    model=model if vectors else None,
                )
                db.add(chunk)
                await db.flush()
                if vectors and i < len(vectors):
                    await db.execute(
                        text(
                            "UPDATE search_chunks SET embedding = CAST(:v AS vector) WHERE id = :id"
                        ),
                        {"v": vector_literal(vectors[i]), "id": chunk.id},
                    )
            done += 1
    finally:
        if client is not None:
            await client.aclose()
    await db.commit()
    return done


async def index_all(
    sessionmaker: async_sessionmaker[AsyncSession], gateway: ModelGateway, settings: Settings
) -> int:
    async with sessionmaker() as db:
        users = list((await db.execute(select(User.id))).scalars())
    total = 0
    for user_id in users:
        async with sessionmaker() as db:
            total += await index_user(db, gateway, settings, user_id)
    return total
