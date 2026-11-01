from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import distinct, func, select

from app.api.deps import CurrentAuth, DbSession, GatewayDep, SettingsDep
from app.models.search import SearchChunk
from app.schemas.search import SearchHitOut, SearchOut, SearchStatus
from app.search.query import Scope, search

router = APIRouter(prefix="/search", tags=["voice & search"])


@router.get("", response_model=SearchOut, summary="Search memories, workspace files and chat files")
async def run_search(
    ctx: CurrentAuth,
    db: DbSession,
    gateway: GatewayDep,
    settings: SettingsDep,
    q: str = Query(..., min_length=1, max_length=500),
    types: str = Query("memory,file,attachment", max_length=40),
    limit: int = Query(10, ge=1, le=50),
) -> SearchOut:
    wanted = tuple(t for t in types.split(",") if t in ("memory", "file", "attachment"))
    hits = await search(
        db, gateway, settings, ctx.user.id, q.strip(), scope=Scope(types=wanted), limit=limit
    )
    return SearchOut(query=q, hits=[SearchHitOut(**h.__dict__) for h in hits])


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
