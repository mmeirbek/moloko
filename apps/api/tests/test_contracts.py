"""Events produced by the backend match packages/agent-contracts (the client contract)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import jsonschema
from fastapi import FastAPI
from sqlalchemy import select

from app.events.bus import envelope
from app.models import AgentEvent, User
from tests.conftest import (
    RecordingQueue,
    add_mock_model,
    create_agent,
    executor_for,
    logged_in_client,
    run_agent,
)

SCHEMAS = Path(__file__).resolve().parents[3] / "packages" / "agent-contracts" / "schemas"


async def test_every_emitted_event_matches_the_envelope_schema(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    schema = json.loads((SCHEMAS / "event-envelope.schema.json").read_text())
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        agent = await create_agent(client)
        task_id = (await run_agent(client, agent["id"], "Contract")).json()["task"]["id"]

    await executor_for(app).execute(uuid.UUID(task_id))
    async with app.state.db.sessionmaker() as db:
        events = list((await db.execute(select(AgentEvent))).scalars())
    assert len({e.type for e in events}) >= 6
    for event in events:
        jsonschema.validate(json.loads(json.dumps(envelope(event), default=str)), schema)
