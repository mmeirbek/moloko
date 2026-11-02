"""An agent's correspondence with other agents (agent page → «Переписка»): questions and
answers (agent_ask), notes (agent_tell) and the Orchestrator's plan messages."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.agent_message import AgentMessage
from app.schemas.agents import AgentMessageItem
from app.schemas.common import decode_cursor, encode_cursor

Direction = Literal["all", "in", "out"]


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def item(
    message: AgentMessage, agent_id: uuid.UUID, names: dict[uuid.UUID, str]
) -> AgentMessageItem:
    content = message.content or {}
    delivered = message.status == "delivered"
    files = [
        str(a["path"])
        for a in content.get("artifacts") or []
        if isinstance(a, dict) and a.get("path")
    ]
    return AgentMessageItem(
        id=message.id,
        created_at=message.created_at,
        direction="out" if message.sender_agent_id == agent_id else "in",
        sender_agent_id=message.sender_agent_id,
        sender_name=names.get(message.sender_agent_id),
        receiver_agent_id=message.receiver_agent_id,
        receiver_name=names.get(message.receiver_agent_id),
        message_type=message.message_type,
        status=message.status,
        error=message.error,
        summary=str(content.get("summary") or ""),
        text=str(content.get("result") or "") if delivered else None,
        files=files,
        task_id=message.task_id,
        consult_task_id=_uuid(content.get("consult_task_id")),
        asker_task_id=_uuid(content.get("asker_task_id")),
        read_at=message.read_at,
    )


async def list_for_agent(
    db: AsyncSession,
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    direction: Direction,
    limit: int,
    cursor: str | None,
) -> tuple[list[AgentMessageItem], str | None]:
    """Newest first; the caller checked that the agent is the owner's."""
    sides = {
        "in": AgentMessage.receiver_agent_id == agent_id,
        "out": AgentMessage.sender_agent_id == agent_id,
    }
    where = sides[direction] if direction in sides else or_(*sides.values())
    query = select(AgentMessage).where(AgentMessage.user_id == user_id, where)
    if cursor:
        at, mid = decode_cursor(cursor)
        query = query.where(
            or_(
                AgentMessage.created_at < at,
                and_(AgentMessage.created_at == at, AgentMessage.id < mid),
            )
        )
    rows = list(
        (
            await db.execute(
                query.order_by(AgentMessage.created_at.desc(), AgentMessage.id.desc()).limit(
                    limit + 1
                )
            )
        ).scalars()
    )
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id)
    ids = {m.sender_agent_id for m in rows} | {m.receiver_agent_id for m in rows}
    names: dict[uuid.UUID, str] = {}
    if ids:
        rows_ = await db.execute(select(Agent.id, Agent.name).where(Agent.id.in_(ids)))
        names = {i: n for i, n in rows_.all()}
    return [item(m, agent_id, names) for m in rows], next_cursor
