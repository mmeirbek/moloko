"""Bringing removed agents back into the office: GET /agents/archived and
POST /agents/{id}/restore."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from app.models import Agent, AgentEvent, AuditLog, User
from tests.conftest import (
    RecordingQueue,
    add_mock_model,
    create_agent,
    csrf_headers,
    drain,
    logged_in_client,
    run_agent,
)

ARCHIVED = "/api/v1/agents/archived"


async def archive(client: httpx.AsyncClient, agent_id: str) -> None:
    resp = await client.delete(f"/api/v1/agents/{agent_id}", headers=await csrf_headers(client))
    assert resp.status_code == 204, resp.text


async def restore(client: httpx.AsyncClient, agent_id: str, **body: Any) -> httpx.Response:
    return await client.post(
        f"/api/v1/agents/{agent_id}/restore",
        json=body or None,
        headers=await csrf_headers(client),
    )


async def events_of(app: FastAPI, agent_id: str) -> list[AgentEvent]:
    async with app.state.db.sessionmaker() as s:
        rows = await s.execute(
            select(AgentEvent)
            .where(AgentEvent.agent_id == uuid.UUID(agent_id))
            .order_by(AgentEvent.seq)
        )
        return list(rows.scalars())


async def audits(app: FastAPI, action: str) -> list[AuditLog]:
    async with app.state.db.sessionmaker() as s:
        rows = await s.execute(
            select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at)
        )
        return list(rows.scalars())


def ids(agents: list[dict[str, Any]]) -> list[str]:
    return [a["id"] for a in agents]


async def test_archived_lists_only_own_persistent_agents_newest_first(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        first = await create_agent(client, name="First")
        second = await create_agent(client, name="Second")
        kept = await create_agent(client, name="Kept")
        assert (await client.get(ARCHIVED)).json() == []

        await archive(client, first["id"])
        await archive(client, second["id"])
        # An orchestrated run leaves archived subagents behind; then the Orchestrator itself
        # is removed. Neither can come back, so neither is listed.
        resp = await client.post(
            "/api/v1/runs",
            json={"title": "Split", "description": "[[mock:plan:2]]"},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 200, resp.text
        await drain(app, queue)
        everyone = (await client.get("/api/v1/agents?include_archived=true")).json()
        subagents = [a for a in everyone if a["agent_type"] == "subagent"]
        assert subagents and all(a["archived_at"] for a in subagents)
        orchestrator = next(a for a in everyone if a["agent_type"] == "orchestrator")
        await archive(client, orchestrator["id"])

        resp = await client.get(ARCHIVED)
        assert resp.status_code == 200, resp.text
        assert ids(resp.json()) == [second["id"], first["id"]]
        assert all(a["archived_at"] for a in resp.json())
        assert ids((await client.get("/api/v1/agents?agent_type=autonomous")).json()) == [
            kept["id"]
        ]


async def test_restore_brings_the_agent_back_idle_with_event_and_audit(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        agent = await create_agent(client, name="Writer", system_prompt="Write well.")
        # It failed its last task, then was removed from the office.
        resp = await run_agent(client, agent["id"], "Oops", "[[mock:error:bad_request]]")
        assert resp.status_code == 200, resp.text
        await drain(app, queue)
        assert (await client.get(f"/api/v1/agents/{agent['id']}")).json()["status"] == "failed"
        await archive(client, agent["id"])

        resp = await restore(client, agent["id"])
        assert resp.status_code == 200, resp.text
        back = resp.json()
        assert back["archived_at"] is None
        assert back["status"] == "idle" and back["current_task_id"] is None
        assert back["name"] == "Writer" and back["system_prompt"] == "Write well."
        assert back["config_version"] == agent["config_version"]  # settings untouched
        assert ids((await client.get("/api/v1/agents")).json()) == [agent["id"]]
        assert (await client.get(ARCHIVED)).json() == []

        # Restoring again: it is already in the office.
        again = await restore(client, agent["id"])
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "agent_not_archived"

        # It works again.
        assert (await run_agent(client, agent["id"], "Next")).status_code == 200
        await drain(app, queue)
        assert (await client.get(f"/api/v1/agents/{agent['id']}")).json()["status"] == "idle"

    events = await events_of(app, agent["id"])
    restored = [
        e
        for e in events
        if e.type == "agent.updated" and e.payload.get("changed") == ["archived_at"]
    ]
    assert len(restored) == 2  # archived, then restored
    assert restored[-1].payload["agent"]["archived_at"] is None
    assert restored[-1].payload["agent"]["status"] == "idle"
    status = [
        e.payload
        for e in events
        if e.type == "agent.status_changed" and e.payload["reason"] == "restored"
    ]
    assert status == [
        {
            "old_status": "failed",
            "new_status": "idle",
            "reason": "restored",
            "agent": status[0]["agent"],
        }
    ]

    rows = await audits(app, "agent.restored")
    assert len(rows) == 1
    assert rows[0].outcome == "success"
    assert rows[0].actor_type == "user" and rows[0].actor_id == owner.id
    assert rows[0].resource_id == agent["id"]
    assert rows[0].details == {"name": "Writer"}


async def test_restore_refuses_a_taken_name_unless_renamed(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        old = await create_agent(client, name="Writer")
        await archive(client, old["id"])
        await create_agent(client, name="Writer")  # a new one took the name meanwhile

        resp = await restore(client, old["id"])
        assert resp.status_code == 409
        error = resp.json()["error"]
        assert error["code"] == "agent_name_taken"
        assert error["details"]["field"] == "name" and error["details"]["name"] == "Writer"
        assert ids((await client.get(ARCHIVED)).json()) == [old["id"]]  # still archived

        resp = await restore(client, old["id"], name="  Writer 2 ")
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "Writer 2"
        assert resp.json()["config_version"] == old["config_version"] + 1
        bad = await restore(client, old["id"], name="")
        assert bad.status_code == 422

    rows = await audits(app, "agent.restored")
    assert rows[0].details == {"name": "Writer 2", "renamed_from": "Writer"}
    restored = [e for e in await events_of(app, old["id"]) if e.type == "agent.updated"][-1]
    assert restored.payload["changed"] == ["archived_at", "name"]
    assert restored.payload["agent"]["name"] == "Writer 2"


async def test_restore_refuses_subagents_orchestrators_and_others_agents(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with app.state.db.sessionmaker() as s:
        other = User(username="other", password_hash="x")
        s.add(other)
        await s.flush()
        theirs = Agent(
            user_id=other.id,
            name="Theirs",
            agent_type="autonomous",
            status="idle",
            archived_at=datetime.now(UTC),
        )
        s.add(theirs)
        await s.commit()

    async with logged_in_client(app) as client:
        await add_mock_model(client)
        resp = await client.post(
            "/api/v1/runs",
            json={"title": "Split", "description": "[[mock:plan:1]]"},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 200, resp.text
        await drain(app, queue)
        everyone = (await client.get("/api/v1/agents?include_archived=true")).json()
        subagent = next(a for a in everyone if a["agent_type"] == "subagent")
        orchestrator = next(a for a in everyone if a["agent_type"] == "orchestrator")
        await archive(client, orchestrator["id"])

        for agent in (subagent, orchestrator):
            resp = await restore(client, agent["id"])
            assert resp.status_code == 409, resp.text
            assert resp.json()["error"]["code"] == "agent_not_restorable"

        for missing in (str(theirs.id), str(uuid.uuid4())):
            resp = await restore(client, missing)
            assert resp.status_code == 404
            assert resp.json()["error"]["code"] == "not_found"
        assert (await client.get(ARCHIVED)).json() == []

        # Unknown fields are refused; CSRF is required like for every change.
        resp = await restore(client, subagent["id"], archived_at=None)
        assert resp.status_code == 422
        resp = await client.post(f"/api/v1/agents/{subagent['id']}/restore")
        assert resp.status_code == 403

    async with app.state.db.sessionmaker() as s:
        row = await s.get(Agent, theirs.id)
        assert row is not None and row.archived_at is not None
    assert await audits(app, "agent.restored") == []
