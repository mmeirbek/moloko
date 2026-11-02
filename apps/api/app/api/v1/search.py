from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import distinct, func, select

from app.api.deps import CurrentAuth, DbSession, GatewayDep, SettingsDep
from app.models.search import SearchChunk
from app.schemas.search import SearchHitOut, SearchOut, SearchStatus
from app.search.query import ALL_TYPES, Hit, Scope, search

router = APIRouter(prefix="/search", tags=["voice & search"])


def hit_out(hit: Hit) -> SearchHitOut:
    meta = hit.meta
    return SearchHitOut(
        source_type=hit.source_type,
        source_id=hit.source_id,
        title=hit.title,
        snippet=hit.snippet,
        score=hit.score,
        mode=hit.mode,
        agent_id=hit.agent_id,
        workspace_id=hit.workspace_id,
        conversation_id=hit.conversation_id,
        peer_agent_id=hit.peer_agent_id,
        run_id=hit.run_id,
        source_at=hit.source_at,
        status=meta.get("status"),
        role=meta.get("role"),
        message_type=meta.get("message_type"),
        task_id=meta.get("task_id"),
        agent_name=meta.get("agent_name"),
        peer_agent_name=meta.get("peer_agent_name"),
    )


@router.get(
    "",
    response_model=SearchOut,
    summary="Search memories, files, chat files and the work history (finished tasks, "
    "agent messages, chat messages)",
)
async def run_search(
    ctx: CurrentAuth,
    db: DbSession,
    gateway: GatewayDep,
    settings: SettingsDep,
    q: str = Query(..., min_length=1, max_length=500),
    types: str = Query("memory,file,attachment", max_length=200),
    limit: int = Query(10, ge=1, le=50),
) -> SearchOut:
    wanted = tuple(t for t in types.split(",") if t in ALL_TYPES)
    hits = await search(
        db, gateway, settings, ctx.user.id, q.strip(), scope=Scope(types=wanted), limit=limit
    )
    return SearchOut(query=q, hits=[hit_out(h) for h in hits])


@router.get("/status", response_model=SearchStatus, summary="What the search index holds")
async def status(ctx: CurrentAuth, db: DbSession) -> SearchStatus:
    row = (
        await db.execute(
            select(
                func.count(),
                func.count(SearchChunk.model),
                func.count(distinct(SearchChunk.source_id)),
            ).where(SearchChunk.user_id == ctx.user.id)
        )
    ).one()
    return SearchStatus(chunks=row[0], with_vectors=row[1], sources=row[2])
