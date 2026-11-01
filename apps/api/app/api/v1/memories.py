from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Response, status

from app.agents.state import MemoryType
from app.api.deps import CurrentAuth, DbSession, SettingsDep
from app.schemas.memories import MemoryCreate, MemoryOut, MemoryRevisionOut, MemoryUpdate
from app.services.memories import MemoryService

router = APIRouter(prefix="/memories", tags=["memory"])


@router.get("", response_model=list[MemoryOut])
async def list_memories(
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    agent_id: uuid.UUID | None = None,
    shared: bool | None = Query(None, description="true: shared only; false: agents' own only"),
    memory_type: MemoryType | None = None,
    project: str | None = Query(None, max_length=100),
    q: str | None = Query(None, max_length=200),
    limit: int = Query(200, ge=1, le=500),
) -> list[MemoryOut]:
    rows = await MemoryService(db, settings).list_memories(
        ctx.user.id,
        agent_id=agent_id,
        shared=shared,
        memory_type=memory_type,
        project=project,
        q=q,
        limit=limit,
    )
    return [MemoryOut.model_validate(m) for m in rows]


@router.post("", response_model=MemoryOut, status_code=status.HTTP_201_CREATED)
async def create_memory(
    body: MemoryCreate, ctx: CurrentAuth, db: DbSession, settings: SettingsDep
) -> MemoryOut:
    return MemoryOut.model_validate(await MemoryService(db, settings).create(ctx.user.id, body))


@router.get("/{memory_id}", response_model=MemoryOut)
async def get_memory(
    memory_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, settings: SettingsDep
) -> MemoryOut:
    return MemoryOut.model_validate(await MemoryService(db, settings).get(ctx.user.id, memory_id))


@router.patch("/{memory_id}", response_model=MemoryOut, summary="Edit (saves a new revision)")
async def update_memory(
    memory_id: uuid.UUID,
    body: MemoryUpdate,
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
) -> MemoryOut:
    memory = await MemoryService(db, settings).update(ctx.user.id, memory_id, body)
    return MemoryOut.model_validate(memory)


@router.delete(
    "/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Forget: deletes the entry and its history",
)
async def delete_memory(
    memory_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, settings: SettingsDep
) -> Response:
    await MemoryService(db, settings).delete(ctx.user.id, memory_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{memory_id}/revisions", response_model=list[MemoryRevisionOut])
async def memory_revisions(
    memory_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, settings: SettingsDep
) -> list[MemoryRevisionOut]:
    rows = await MemoryService(db, settings).revisions(ctx.user.id, memory_id)
    return [MemoryRevisionOut.model_validate(r) for r in rows]
