"""Event log write path (spec 10.3).

    state change + event INSERT  →  one DB transaction  →  after COMMIT: Redis pub/sub

* ``emit()`` adds an event to the caller's transaction (taking an advisory lock first,
  so concurrent writers commit events in ``seq`` order).
* ``commit()`` commits and then publishes what was committed. Events of a rolled-back
  transaction are dropped and never published.
* ``publish_ephemeral()`` sends stream-only events (``chat.message_delta``) that are not stored.

If Redis is down, events are still in PostgreSQL; clients catch up on reconnect.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import event as sa_event
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session as SyncSession

from app.models.event import AgentEvent

logger = logging.getLogger("moloko.events")

EVENT_VERSION = 1
_ADVISORY_LOCK_KEY = 72_015_001  # arbitrary, unique to the event log
_LOCK = "moloko_event_lock"
_PENDING = "moloko_pending_events"
_COMMITTED = "moloko_committed_events"


def channel(user_id: uuid.UUID | str) -> str:
    return f"moloko:events:{user_id}"


def envelope(ev: AgentEvent) -> dict[str, Any]:
    return {
        "id": str(ev.id),
        "seq": ev.seq,
        "type": ev.type,
        "version": ev.version,
        "timestamp": ev.created_at.isoformat() if ev.created_at else None,
        "agent_id": str(ev.agent_id) if ev.agent_id else None,
        "task_id": str(ev.task_id) if ev.task_id else None,
        "run_id": str(ev.run_id) if ev.run_id else None,
        "payload": ev.payload,
    }


class EventPublisher:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def publish(self, user_id: uuid.UUID | str, data: dict[str, Any]) -> None:
        try:
            await self.redis.publish(channel(user_id), json.dumps(data, default=str))
        except Exception as exc:  # noqa: BLE001 — events are durable in PostgreSQL anyway
            logger.warning(
                "event_publish_failed",
                extra={"error": type(exc).__name__, "type": data.get("type")},
            )


_publisher: EventPublisher | None = None


def set_publisher(publisher: EventPublisher | None) -> None:
    global _publisher
    _publisher = publisher


def get_publisher() -> EventPublisher | None:
    return _publisher


@sa_event.listens_for(SyncSession, "after_commit")
def _after_commit(session: SyncSession) -> None:
    pending = session.info.pop(_PENDING, [])
    if pending:
        session.info.setdefault(_COMMITTED, []).extend(pending)
    session.info.pop(_LOCK, None)


@sa_event.listens_for(SyncSession, "after_rollback")
def _after_rollback(session: SyncSession) -> None:
    session.info.pop(_PENDING, None)
    session.info.pop(_LOCK, None)


async def emit(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    type: str,
    payload: dict[str, Any] | None = None,
    agent_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
) -> AgentEvent:
    if not db.info.get(_LOCK):
        await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _ADVISORY_LOCK_KEY})
        db.info[_LOCK] = True
    ev = AgentEvent(
        user_id=user_id,
        type=type,
        version=EVENT_VERSION,
        agent_id=agent_id,
        task_id=task_id,
        run_id=run_id,
        payload=payload or {},
    )
    db.add(ev)
    await db.flush()
    db.info.setdefault(_PENDING, []).append(ev)
    return ev


async def publish_committed(db: AsyncSession) -> None:
    committed: list[AgentEvent] = db.info.pop(_COMMITTED, [])
    publisher = get_publisher()
    if publisher is None:
        return
    for ev in committed:
        await publisher.publish(ev.user_id, envelope(ev))


async def commit(db: AsyncSession) -> None:
    """Commit the transaction, then publish its events."""
    await db.commit()
    await publish_committed(db)


async def publish_ephemeral(
    user_id: uuid.UUID,
    type: str,
    payload: dict[str, Any],
    *,
    agent_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
) -> None:
    publisher = get_publisher()
    if publisher is None:
        return
    await publisher.publish(
        user_id,
        {
            "id": str(uuid.uuid4()),
            "seq": None,
            "type": type,
            "version": EVENT_VERSION,
            "timestamp": datetime.now(UTC).isoformat(),
            "agent_id": str(agent_id) if agent_id else None,
            "task_id": str(task_id) if task_id else None,
            "run_id": str(run_id) if run_id else None,
            "payload": payload,
        },
    )
