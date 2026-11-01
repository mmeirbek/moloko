from __future__ import annotations

import uuid

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import CurrentAuth, DbSession
from app.api.v1.tasks import event_out
from app.core.errors import NotFound
from app.models.event import AgentEvent
from app.schemas.tasks import EventOut

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[EventOut], summary="Event log (resume with after_seq)")
async def list_events(
    ctx: CurrentAuth,
    db: DbSession,
    after_seq: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    run_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    latest: bool = Query(
        False, description="the most recent `limit` events (still oldest → newest)"
    ),
) -> list[EventOut]:
    query = select(AgentEvent).where(AgentEvent.user_id == ctx.user.id, AgentEvent.seq > after_seq)
    if run_id is not None:
        query = query.where(AgentEvent.run_id == run_id)
    if task_id is not None:
        query = query.where(AgentEvent.task_id == task_id)
    if agent_id is not None:
        query = query.where(AgentEvent.agent_id == agent_id)
    if latest:
        rows = list(
            (await db.execute(query.order_by(AgentEvent.seq.desc()).limit(limit))).scalars()
        )
        rows.reverse()
        return [event_out(e) for e in rows]
    rows_asc = await db.execute(query.order_by(AgentEvent.seq).limit(limit))
    return [event_out(e) for e in rows_asc.scalars()]


@router.get("/{event_id}", response_model=EventOut)
async def get_event(event_id: uuid.UUID, ctx: CurrentAuth, db: DbSession) -> EventOut:
    event = await db.get(AgentEvent, event_id)
    if event is None or event.user_id != ctx.user.id:
        raise NotFound("Event not found.")
    return event_out(event)
