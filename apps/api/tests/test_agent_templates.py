"""Own agent templates: POST /agents/{id}/save-template, GET /agents/templates (built-in +
own), POST /agents/from-template with an own template, DELETE /agents/templates/{id}."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from app.models import AuditLog, SavedAgentTemplate, User
from tests.conftest import (
    AppFactory,
    RecordingQueue,
    add_mock_model,
    create_agent,
    csrf_headers,
    logged_in_client,
)

TEMPLATES = "/api/v1/agents/templates"


async def save_template(client: httpx.AsyncClient, agent_id: str, **body: Any) -> httpx.Response:
    return await client.post(
        f"/api/v1/agents/{agent_id}/save-template",
        json=body or None,
        headers=await csrf_headers(client),
    )


async def from_template(client: httpx.AsyncClient, key: str, **body: Any) -> httpx.Response:
    return await client.post(
        "/api/v1/agents/from-template",
        json={"template": key, **body},
        headers=await csrf_headers(client),
    )


async def audits(app: FastAPI, action: str) -> list[AuditLog]:
    async with app.state.db.sessionmaker() as s:
        rows = await s.execute(
            select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at)
        )
        return list(rows.scalars())


async def configured_agent(client: httpx.AsyncClient) -> dict[str, Any]:
    model = await add_mock_model(client)
    return await create_agent(
        client,
        name="Dev",
        description="Writes code",
        specialization="coding",
        model_config_id=model["id"],
        system_prompt="Be precise.",
        autonomy_level="balanced",
        allowed_tools=["fs_read", "fs_write"],
        tool_overrides={"fs_write": "approve"},
        limits={"max_steps": 10, "run_timeout_seconds": 600},
        memory_settings={"include_shared": False, "projects": ["moloko"]},
        monthly_budget_usd="7.50",
    )


async def test_save_list_and_use_an_own_template(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        agent = await configured_agent(client)
        memory = await client.post(
            "/api/v1/memories",
            json={
                "memory_type": "agent",
                "agent_id": agent["id"],
                "title": "Fact",
                "content": "The owner likes tests.",
            },
            headers=await csrf_headers(client),
        )
        assert memory.status_code == 201, memory.text

        resp = await save_template(client, agent["id"])
        assert resp.status_code == 201, resp.text
        saved = resp.json()
        assert saved["source"] == "own" and saved["key"] == saved["id"]
        assert saved["name"] == "Dev" and saved["monthly_budget_usd"] == "7.50"
        assert saved["allowed_tools"] == ["fs_read", "fs_write"]

        listed = (await client.get(f"{TEMPLATES}?locale=en")).json()
        sources = [t["source"] for t in listed]
        assert sources == ["builtin"] * (len(listed) - 1) + ["own"]
        assert listed[0]["key"] == "researcher" and listed[0]["id"] is None
        assert listed[-1]["key"] == saved["id"]

        # The office already has "Dev": the new one is "Dev 2", with the same configuration.
        resp = await from_template(client, saved["key"])
        assert resp.status_code == 201, resp.text
        copy = resp.json()
        assert copy["name"] == "Dev 2" and copy["agent_type"] == "autonomous"
        assert copy["status"] == "idle" and copy["current_task_id"] is None
        for field in (
            "description",
            "specialization",
            "model_config_id",
            "system_prompt",
            "autonomy_level",
            "allowed_tools",
            "permissions",
            "limits",
            "memory_settings",
            "monthly_budget_usd",
        ):
            assert copy[field] == agent[field], field
        # Memory and history are not part of a template.
        own_memories = (await client.get(f"/api/v1/memories?agent_id={copy['id']}")).json()
        assert own_memories == []

    saved_rows = await audits(app, "agent_template.saved")
    assert len(saved_rows) == 1 and saved_rows[0].details["name"] == "Dev"
    created = [r for r in await audits(app, "agent.created") if r.resource_id == copy["id"]]
    assert created[0].details["template_source"] == "own"
    assert created[0].details["template"] == saved["id"]


async def test_template_names_are_unique_per_owner(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        agent = await create_agent(client, name="Writer")
        assert (await save_template(client, agent["id"])).status_code == 201
        again = await save_template(client, agent["id"])
        assert again.status_code == 409
        error = again.json()["error"]
        assert error["code"] == "template_name_taken" and error["details"]["name"] == "Writer"
        renamed = await save_template(client, agent["id"], name="  Writer (short)  ")
        assert renamed.status_code == 201 and renamed.json()["name"] == "Writer (short)"
        names = [t["name"] for t in (await client.get(TEMPLATES)).json() if t["source"] == "own"]
        assert sorted(names) == ["Writer", "Writer (short)"]


async def test_delete_an_own_template(app: FastAPI, owner: User, queue: RecordingQueue) -> None:
    async with logged_in_client(app) as client:
        agent = await create_agent(client, name="Temp")
        template = (await save_template(client, agent["id"])).json()
        made = (await from_template(client, template["key"])).json()

        url = f"{TEMPLATES}/{template['id']}"
        resp = await client.delete(url, headers=await csrf_headers(client))
        assert resp.status_code == 204
        assert [t for t in (await client.get(TEMPLATES)).json() if t["source"] == "own"] == []
        again = await client.delete(url, headers=await csrf_headers(client))
        assert again.status_code == 404
        assert (await from_template(client, template["key"])).status_code == 404
        # Agents made from it stay.
        assert (await client.get(f"/api/v1/agents/{made['id']}")).status_code == 200
    deleted = await audits(app, "agent_template.deleted")
    assert len(deleted) == 1 and deleted[0].details == {"name": "Temp"}


async def test_other_owners_templates_are_invisible(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with app.state.db.sessionmaker() as db:
        other = User(username="other", password_hash="not-a-real-hash")
        db.add(other)
        await db.flush()
        row = SavedAgentTemplate(user_id=other.id, name="Secret", system_prompt="hidden")
        db.add(row)
        await db.commit()
        other_id = str(row.id)
    async with logged_in_client(app) as client:
        listed = (await client.get(TEMPLATES)).json()
        assert all(t["source"] == "builtin" for t in listed)
        assert (await from_template(client, other_id)).status_code == 404
        resp = await client.delete(f"{TEMPLATES}/{other_id}", headers=await csrf_headers(client))
        assert resp.status_code == 404
        assert (await from_template(client, "no-such-template")).status_code == 404


async def test_only_persistent_agents_can_be_saved(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        started = await client.post(
            "/api/v1/runs", json={"title": "Hello"}, headers=await csrf_headers(client)
        )
        assert started.status_code == 200, started.text
        agents = (await client.get("/api/v1/agents")).json()
        orchestrator = next(a for a in agents if a["agent_type"] == "orchestrator")
        resp = await save_template(client, orchestrator["id"])
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "agent_not_templatable"
        missing = await save_template(client, str(uuid.uuid4()))
        assert missing.status_code == 404


async def test_template_limit(app_factory: AppFactory, owner: User) -> None:
    app = await app_factory(agent_templates_max=1)
    app.state.queue = RecordingQueue()
    async with logged_in_client(app) as client:
        agent = await create_agent(client, name="One")
        assert (await save_template(client, agent["id"])).status_code == 201
        resp = await save_template(client, agent["id"], name="Two")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "template_limit_reached"
        assert resp.json()["error"]["details"] == {"max": 1}


async def test_an_old_template_is_adapted_to_today(app_factory: AppFactory, owner: User) -> None:
    """A tool removed since and limits above today's global ones do not block the drop."""
    app = await app_factory(max_steps_per_run=20)
    app.state.queue = RecordingQueue()
    async with logged_in_client(app) as client:
        agent = await create_agent(client, name="Old", allowed_tools=["fs_read"])
        template = (await save_template(client, agent["id"])).json()
        async with app.state.db.sessionmaker() as db:
            row = await db.get(SavedAgentTemplate, uuid.UUID(template["id"]))
            assert row is not None
            row.allowed_tools = ["fs_read", "gone_mcp_tool"]
            row.permissions = {"tools": {"gone_mcp_tool": "deny", "fs_read": "approve"}}
            row.limits = {"max_steps": 500}
            await db.commit()
        resp = await from_template(client, template["key"], name="Fresh")
        assert resp.status_code == 201, resp.text
        made = resp.json()
        assert made["name"] == "Fresh"
        assert made["allowed_tools"] == ["fs_read"]
        assert made["permissions"] == {"tools": {"fs_read": "approve"}}
        assert made["limits"] == {"max_steps": 20}
