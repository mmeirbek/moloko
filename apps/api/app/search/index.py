"""Keeps `search_chunks` in step with its sources (worker job, every few seconds).

Sources: memories, text files in workspaces, and text/PDF files sent in chats. Each source
is split into chunks; when semantic search is on and an OpenAI-type provider exists, the
chunks also get embeddings (pgvector). Without one, chunks are still stored and found by
words. Only changed sources are re-indexed (content hash), deleted ones are removed.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models.chat import Attachment
from app.models.memory import Memory
from app.models.search import SearchChunk, vector_literal
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
    attachments = await db.execute(
        select(Attachment).where(
            Attachment.user_id == user_id,
            Attachment.message_id.is_not(None),
            Attachment.kind.in_(("text", "pdf")),
        )
    )
    for a in attachments.scalars():
        if a.text.strip():
            out.append(
                Source(
                    "attachment",
                    a.id,
                    a.filename,
                    a.text,
                    a.sha256,
                    conversation_id=a.conversation_id,
                )
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
    gone = [key for key in indexed if key not in wanted]
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

    client = ai_services.adapter(gateway, target) if (target and model) else None
    done = 0
    try:
        for source in stale:
            pieces = chunk_text(source.text, settings.search_chunk_chars)
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
                    title=source.title[:300],
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
