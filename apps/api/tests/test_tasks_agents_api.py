from __future__ import annotations

import uuid

from fastapi import FastAPI
from sqlalchemy import select

from app.models import AgentEvent, AuditLog, User
from tests.conftest import (
    RecordingQueue,
    add_mock_model,
    create_agent,
    csrf_headers,
    executor_for,
    logged_in_client,
    run_agent,
)


async def test_agent_crud_and_archive(app: FastAPI, owner: User, queue: RecordingQueue) -> None:
    async with logged_in_client(app) as client:
        model = await add_mock_model(client)
        agent = await create_agent(
            client,
            name="Researcher",
            model_config_id=model["id"],
            autonomy_level="balanced",
            allowed_tools=["fs_read", "fs_read"],
            limits={"max_steps": 10},
        )
        assert agent["agent_type"] == "autonomous" and agent["status"] == "idle"
        assert agent["allowed_tools"] == ["fs_read"]  # de-duplicated
        assert agent["limits"] == {"max_steps": 10}

        resp = await client.patch(
            f"/api/v1/agents/{agent['id']}",
            json={"system_prompt": "Cite sources."},
            headers=await csrf_headers(client),
        )
        assert resp.json()["config_version"] == 2

        sub = await client.post(
            "/api/v1/agents",
            json={"name": "S", "agent_type": "subagent"},
            headers=await csrf_headers(client),
        )
        assert sub.status_code == 409

        bad_model = await client.post(
            "/api/v1/agents",
            json={"name": "X", "model_config_id": str(uuid.uuid4())},
            headers=await csrf_headers(client),
        )
        assert bad_model.json()["error"]["code"] == "model_unavailable"

        assert (
            await client.delete(f"/api/v1/agents/{agent['id']}", headers=await csrf_headers(client))
        ).status_code == 204
        assert (await client.get("/api/v1/agents")).json() == []
        archived = (await client.get("/api/v1/agents?include_archived=true")).json()
        assert archived[0]["archived_at"] is not None
        blocked = await run_agent(client, agent["id"], "After delete")
        assert blocked.status_code == 409

    async with app.state.db.sessionmaker() as db:
        actions = {a.action for a in (await db.execute(select(AuditLog))).scalars()}
        events = [
            e.type
            for e in (await db.execute(select(AgentEvent).order_by(AgentEvent.seq))).scalars()
        ]
    assert {"agent.created", "agent.updated", "agent.deleted"} <= actions
    assert events[:2] == ["agent.created", "agent.updated"]


async def test_cannot_delete_a_busy_agent(app: FastAPI, owner: User, queue: RecordingQueue) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        agent = await create_agent(client)
        await run_agent(client, agent["id"], "Busy")
        resp = await client.delete(
            f"/api/v1/agents/{agent['id']}", headers=await csrf_headers(client)
        )
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "agent_busy"


async def test_task_create_list_filter_search_and_history(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        agent = await create_agent(client)
        draft = (
            await client.post(
                "/api/v1/tasks",
                json={"title": "Write report", "description": "Q3 numbers"},
                headers=await csrf_headers(client),
            )
        ).json()
        assert draft["status"] == "created" and queue.enqueued == []

        edited = await client.patch(
            f"/api/v1/tasks/{draft['id']}",
            json={"agent_id": agent["id"], "priority": 1},
            headers=await csrf_headers(client),
        )
        assert edited.json()["agent_id"] == agent["id"]

        run = await client.post(
            f"/api/v1/agents/{agent['id']}/run",
            json={"task_id": draft["id"]},
            headers=await csrf_headers(client),
        )
        assert run.status_code == 200 and run.json()["task"]["status"] == "queued"
        await executor_for(app).execute(uuid.UUID(draft["id"]))

        other = (
            await client.post(
                "/api/v1/tasks", json={"title": "Plan trip"}, headers=await csrf_headers(client)
            )
        ).json()
        await client.post(f"/api/v1/tasks/{other['id']}/cancel", headers=await csrf_headers(client))

        def ids(resp: object) -> set[str]:
            return {t["id"] for t in resp.json()["items"]}  # type: ignore[attr-defined]

        assert ids(await client.get("/api/v1/tasks?status=completed")) == {draft["id"]}
        assert ids(await client.get("/api/v1/tasks?status=cancelled")) == {other["id"]}
        assert ids(await client.get("/api/v1/tasks?status=active")) == set()
        assert ids(await client.get("/api/v1/tasks?q=REPORT")) == {draft["id"]}
        assert ids(await client.get("/api/v1/tasks?q=100%25")) == set()
        assert ids(await client.get(f"/api/v1/tasks?agent_id={agent['id']}")) == {draft["id"]}

        history = (await client.get(f"/api/v1/tasks/{draft['id']}/events")).json()
        seqs = [e["seq"] for e in history]
        assert seqs == sorted(seqs)
        assert {"task.created", "task.updated", "task.completed", "agent.message"} <= {
            e["type"] for e in history
        }
        after = (
            await client.get(f"/api/v1/events?after_seq={seqs[2]}&task_id={draft['id']}")
        ).json()
        assert all(e["seq"] > seqs[2] for e in after)
        latest = (
            await client.get(f"/api/v1/events?agent_id={agent['id']}&latest=true&limit=2")
        ).json()
        assert len(latest) == 2 and latest[0]["seq"] < latest[1]["seq"]
        all_agent = (await client.get(f"/api/v1/events?agent_id={agent['id']}&limit=500")).json()
        assert [e["id"] for e in latest] == [e["id"] for e in all_agent[-2:]]
        one = (await client.get(f"/api/v1/events/{history[0]['id']}")).json()
        assert one["id"] == history[0]["id"]

        finished_edit = await client.patch(
            f"/api/v1/tasks/{draft['id']}", json={"title": "x"}, headers=await csrf_headers(client)
        )
        assert finished_edit.status_code == 409


async def test_retry_creates_a_new_attempt_and_keeps_history(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        agent = await create_agent(client)
        failed_id = (
            await run_agent(client, agent["id"], "Flaky", "[[mock:error:unavailable]]")
        ).json()["task"]["id"]
        await executor_for(app).execute(uuid.UUID(failed_id))
        assert (await client.get(f"/api/v1/tasks/{failed_id}")).json()["task"]["status"] == "failed"

        not_failed = await client.post(
            f"/api/v1/tasks/{uuid.uuid4()}/retry", headers=await csrf_headers(client)
        )
        assert not_failed.status_code == 404

        retry = (
            await client.post(
                f"/api/v1/tasks/{failed_id}/retry", headers=await csrf_headers(client)
            )
        ).json()
        assert retry["id"] != failed_id
        assert (retry["attempt"], retry["retry_of_id"], retry["status"]) == (2, failed_id, "queued")
        old = (await client.get(f"/api/v1/tasks/{failed_id}")).json()["task"]
        assert old["status"] == "failed"  # history kept

        again = await client.post(
            f"/api/v1/tasks/{retry['id']}/retry", headers=await csrf_headers(client)
        )
        assert again.status_code == 409  # only failed/cancelled tasks can be retried


async def test_chat_answers_are_in_the_event_log(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        chat = (
            await client.post("/api/v1/chats", json={}, headers=await csrf_headers(client))
        ).json()
        async with client.stream(
            "POST",
            f"/api/v1/chats/{chat['id']}/messages",
            json={"content": "hi"},
            headers=await csrf_headers(client),
        ) as resp:
            await resp.aread()
    async with app.state.db.sessionmaker() as db:
        events = list((await db.execute(select(AgentEvent))).scalars())
    completed = [e for e in events if e.type == "chat.message_completed"]
    assert len(completed) == 1
    assert completed[0].payload["message"]["content"] == "Echo: hi"
    assert not any(e.type == "chat.message_delta" for e in events)  # deltas are stream-only


async def test_agent_templates_add_idle_agents_that_wait_for_a_task(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        templates = (await client.get("/api/v1/agents/templates?locale=ru")).json()
        assert [t["key"] for t in templates] == [
            "researcher",
            "programmer",
            "reviewer",
            "translator",
        ]
        assert templates[0]["name"] == "Исследователь"
        english = (await client.get("/api/v1/agents/templates?locale=en")).json()
        assert english[3]["name"] == "Translator"

        headers = await csrf_headers(client)
        first = await client.post(
            "/api/v1/agents/from-template", json={"template": "researcher"}, headers=headers
        )
        assert first.status_code == 201, first.text
        agent = first.json()
        assert agent["name"] == "Исследователь" and agent["status"] == "idle"
        assert agent["agent_type"] == "autonomous" and agent["autonomy_level"] == "supervised"
        assert "web_search" in agent["allowed_tools"]
        second = await client.post(
            "/api/v1/agents/from-template", json={"template": "researcher"}, headers=headers
        )
        assert second.json()["name"] == "Исследователь 2"  # names stay unique

        unknown = await client.post(
            "/api/v1/agents/from-template", json={"template": "astronaut"}, headers=headers
        )
        assert unknown.status_code == 404
        # nothing runs until the owner gives the agent a task
        assert queue.enqueued == []
        tasks = (await client.get(f"/api/v1/tasks?agent_id={agent['id']}&status=all")).json()
        assert tasks["items"] == []
