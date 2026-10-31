"""Current state for a (re)connecting client (spec 11 ``snapshot``)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.engine import agent_payload, run_payload, task_payload
from app.agents.state import ACTIVE_TASK
from app.models.agent import Agent, AgentRun
from app.models.event import AgentEvent
from app.models.task import Task

RECENT_FINISHED = 50


async def current_seq(db: AsyncSession, user_id: uuid.UUID) -> int:
    value = (
        await db.execute(select(func.max(AgentEvent.seq)).where(AgentEvent.user_id == user_id))
    ).scalar()
    return int(value or 0)


async def missed_count(db: AsyncSession, user_id: uuid.UUID, after: int, cap: int) -> int:
    """How many of the user's events come after ``after`` (counting stops at ``cap``)."""
    inner = (
        select(AgentEvent.seq)
        .where(AgentEvent.user_id == user_id, AgentEvent.seq > after)
        .limit(cap)
        .subquery()
    )
    return int((await db.execute(select(func.count()).select_from(inner))).scalar_one())


async def build_snapshot(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    seq = await current_seq(db, user_id)
    agents = (
        await db.execute(
            select(Agent)
            .where(Agent.user_id == user_id, Agent.archived_at.is_(None))
            .order_by(Agent.created_at)
        )
    ).scalars()
    active_statuses = [s.value for s in ACTIVE_TASK]
    active = (
        await db.execute(
            select(Task).where(Task.user_id == user_id, Task.status.in_(active_statuses))
        )
    ).scalars()
    recent = (
        await db.execute(
            select(Task)
            .where(Task.user_id == user_id, Task.status.not_in(active_statuses))
            .order_by(Task.updated_at.desc())
            .limit(RECENT_FINISHED)
        )
    ).scalars()
    runs = (
        await db.execute(
            select(AgentRun).where(
                AgentRun.user_id == user_id, AgentRun.status.in_(active_statuses)
            )
        )
    ).scalars()
    return {
        "type": "snapshot",
        "seq": seq,
        "agents": [agent_payload(a) for a in agents],
        "tasks": [task_payload(t) for t in [*active, *recent]],
        "runs": [run_payload(r) for r in runs],
        "approvals": [],  # Sprint 7
    }
