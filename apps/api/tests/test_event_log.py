from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.redis import create_redis
from app.events import bus
from app.models import AgentEvent, User
from tests.conftest import TEST_REDIS_URL


async def _emit(app: FastAPI, user: User, type_: str, **payload: object) -> None:
    async with app.state.db.sessionmaker() as db:
        await bus.emit(db, user_id=user.id, type=type_, payload=dict(payload))
        await bus.commit(db)


async def test_committed_events_get_increasing_seq_and_are_published(
    app: FastAPI, owner: User
) -> None:
    redis = create_redis(TEST_REDIS_URL, socket_timeout=None)
    pubsub = redis.pubsub()
    await pubsub.subscribe(bus.channel(owner.id))
    await pubsub.get_message(timeout=1)  # subscribe confirmation

    await _emit(app, owner, "agent.created", n=1)
    await _emit(app, owner, "agent.updated", n=2)

    received = []
    for _ in range(2):
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=2)
        assert message is not None
        received.append(json.loads(message["data"]))
    await pubsub.aclose()  # type: ignore[no-untyped-call]
    await redis.aclose()

    assert [e["type"] for e in received] == ["agent.created", "agent.updated"]
    assert received[1]["seq"] > received[0]["seq"]
    assert set(received[0]) == {
        "id",
        "seq",
        "type",
        "version",
        "timestamp",
        "agent_id",
        "task_id",
        "run_id",
        "payload",
    }
    assert received[0]["version"] == 1


async def test_rolled_back_events_are_neither_stored_nor_published(
    app: FastAPI, owner: User
) -> None:
    async with app.state.db.sessionmaker() as db:
        await bus.emit(db, user_id=owner.id, type="agent.created")
        await db.rollback()
        await bus.emit(db, user_id=owner.id, type="agent.updated")
        await bus.commit(db)
    async with app.state.db.sessionmaker() as db:
        types = [e.type for e in (await db.execute(select(AgentEvent))).scalars()]
    assert types == ["agent.updated"]


async def test_concurrent_writers_commit_in_seq_order(app: FastAPI, owner: User) -> None:
    """The advisory lock makes the second writer wait for the first commit."""
    first = app.state.db.sessionmaker()
    second = app.state.db.sessionmaker()
    async with first, second:
        await bus.emit(first, user_id=owner.id, type="task.updated", payload={"who": "first"})
        waiting = asyncio.create_task(_second(second, owner.id))
        await asyncio.sleep(0.3)
        assert not waiting.done(), "second writer must wait for the first transaction"
        await bus.commit(first)
        await asyncio.wait_for(waiting, timeout=5)
    async with app.state.db.sessionmaker() as db:
        rows = list((await db.execute(select(AgentEvent).order_by(AgentEvent.seq))).scalars())
    assert [r.payload["who"] for r in rows] == ["first", "second"]


async def _second(db: object, user_id: uuid.UUID) -> None:
    await bus.emit(db, user_id=user_id, type="task.updated", payload={"who": "second"})  # type: ignore[arg-type]
    await bus.commit(db)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "statement", ["UPDATE agent_events SET type = 'x'", "DELETE FROM agent_events"]
)
async def test_event_log_is_append_only(app: FastAPI, owner: User, statement: str) -> None:
    await _emit(app, owner, "agent.created")
    async with app.state.db.sessionmaker() as db:
        with pytest.raises(DBAPIError, match="append-only"):
            await db.execute(text(statement))


async def test_events_survive_redis_outage(app: FastAPI, owner: User) -> None:
    from app.events.bus import EventPublisher, get_publisher, set_publisher

    original = get_publisher()
    set_publisher(EventPublisher(create_redis("redis://127.0.0.1:1/0")))
    try:
        await _emit(app, owner, "agent.created")  # must not raise
    finally:
        set_publisher(original)
    async with app.state.db.sessionmaker() as db:
        assert (await db.execute(select(AgentEvent))).scalar_one().type == "agent.created"
