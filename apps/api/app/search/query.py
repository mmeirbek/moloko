"""Search over `search_chunks`: by meaning (pgvector cosine distance) when embeddings
exist for the current model, otherwise by words (PostgreSQL full text, 'simple' config so
Russian and English both work). Results are grouped per source (best chunk wins)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import ColumnElement, and_, false, func, literal, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.search import SearchChunk, vector_literal
from app.providers.gateway import ModelGateway
from app.services import ai_services


@dataclass(frozen=True)
class Scope:
    """Which chunks a search may see. The owner sees everything; an agent only its own
    memory (plus shared/project memory it is allowed) and its workspaces' files."""

    types: tuple[str, ...] = ("memory", "file", "attachment")
    memory_filter: ColumnElement[bool] | None = None
    workspace_ids: tuple[uuid.UUID, ...] | None = None  # None = any


@dataclass
class Hit:
    source_type: str
    source_id: uuid.UUID
    title: str
    snippet: str
    score: float
    mode: str
    agent_id: uuid.UUID | None = None
    workspace_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _where(user_id: uuid.UUID, scope: Scope) -> list[ColumnElement[bool]]:
    parts: list[ColumnElement[bool]] = []
    if "memory" in scope.types:
        cond = SearchChunk.source_type == "memory"
        parts.append(and_(cond, scope.memory_filter) if scope.memory_filter is not None else cond)
    if "file" in scope.types:
        cond = SearchChunk.source_type == "file"
        if scope.workspace_ids is not None:
            cond = and_(cond, SearchChunk.workspace_id.in_(scope.workspace_ids or [uuid.uuid4()]))
        parts.append(cond)
    if "attachment" in scope.types:
        parts.append(SearchChunk.source_type == "attachment")
    return [SearchChunk.user_id == user_id, or_(*parts) if parts else false()]


def _snippet(body: str, query: str, size: int = 280) -> str:
    low = body.lower()
    words = [w for w in query.lower().split() if len(w) > 2]
    at = min((low.find(w) for w in words if low.find(w) >= 0), default=0)
    start = max(0, at - size // 3)
    piece = body[start : start + size].strip()
    return ("…" if start > 0 else "") + piece + ("…" if start + size < len(body) else "")


async def search(
    db: AsyncSession,
    gateway: ModelGateway,
    settings: Settings,
    user_id: uuid.UUID,
    query: str,
    *,
    scope: Scope | None = None,
    limit: int | None = None,
) -> list[Hit]:
    scope = scope or Scope()
    limit = min(limit or settings.search_max_results, 50)
    where = _where(user_id, scope)
    hits: dict[tuple[str, uuid.UUID], Hit] = {}

    target = None
    try:
        target = await ai_services.resolve(db, gateway, settings, user_id)
    except ai_services.AiServiceUnavailable:
        target = None
    if target and target.semantic_search:
        has_vectors = (
            await db.execute(
                select(func.count())
                .select_from(SearchChunk)
                .where(*where, SearchChunk.model == target.embedding_model)
            )
        ).scalar()
        if has_vectors:
            client = ai_services.adapter(gateway, target)
            try:
                vectors, used = await client.embed(
                    [query], target.embedding_model, target.embedding_dimensions
                )
            finally:
                await client.aclose()
            db.add(ai_services.ledger_row(user_id, target, "search", target.embedding_model, used))
            await db.commit()
            distance = SearchChunk.embedding.op("<=>")(
                text("CAST(:qv AS vector)").bindparams(qv=vector_literal(vectors[0]))
            )
            rows = (
                await db.execute(
                    select(SearchChunk, distance.label("d"))
                    .where(*where, SearchChunk.model == target.embedding_model)
                    .order_by(distance)
                    .limit(limit * 4)
                )
            ).all()
            for chunk, d in rows:
                key = (chunk.source_type, chunk.source_id)
                score = 1.0 - float(d)
                if key not in hits or hits[key].score < score:
                    hits[key] = _hit(chunk, query, score, "semantic")
    if not hits:  # words: full text first, then a plain substring match
        tsq = func.plainto_tsquery("simple", query)
        doc = func.to_tsvector("simple", SearchChunk.title + " " + SearchChunk.text)
        rank = func.ts_rank(doc, tsq)
        rows = (
            await db.execute(
                select(SearchChunk, rank.label("r"))
                .where(*where, doc.op("@@")(tsq))
                .order_by(rank.desc())
                .limit(limit * 4)
            )
        ).all()
        if not rows:
            like = f"%{query.strip()[:100]}%"
            rows = (
                await db.execute(
                    select(SearchChunk, literal(0.1).label("r"))
                    .where(*where, or_(SearchChunk.text.ilike(like), SearchChunk.title.ilike(like)))
                    .limit(limit * 4)
                )
            ).all()
        for chunk, r in rows:
            key = (chunk.source_type, chunk.source_id)
            score = float(r or 0)
            if key not in hits or hits[key].score < score:
                hits[key] = _hit(chunk, query, score, "words")
    return sorted(hits.values(), key=lambda h: h.score, reverse=True)[:limit]


def _hit(chunk: SearchChunk, query: str, score: float, mode: str) -> Hit:
    return Hit(
        source_type=chunk.source_type,
        source_id=chunk.source_id,
        title=chunk.title,
        snippet=_snippet(chunk.text, query),
        score=round(score, 4),
        mode=mode,
        agent_id=chunk.agent_id,
        workspace_id=chunk.workspace_id,
        conversation_id=chunk.conversation_id,
    )
