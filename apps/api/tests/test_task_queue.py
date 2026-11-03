"""Tasks wait in line for a busy agent, and the Orchestrator runs several plans at once
(owner's decision 2026-11-03, app/agents/waiting.py)."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.agents import waiting
from app.models import Agent, Message, Task, User
from tests.conftest import (
    RecordingQueue,
    add_mock_model,
    create_agent,
    csrf_headers,
    drain,
    executor_for,
    logged_in_client,
    run_agent,
)


async def start_run(client: httpx.AsyncClient, title: str, description: str = "") -> dict[str, Any]:
    resp = await client.post(
        "/api/v1/runs",
        json={"title": title, "description": description},
        headers=await csrf_headers(client),
    )
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


async def task_of(app: FastAPI, task_id: str) -> Task:
    async with app.state.db.sessionmaker() as db:
        task = await db.get(Task, uuid.UUID(task_id))
        assert task is not None
        return task


async def orchestrator(app: FastAPI) -> Agent:
    async with app.state.db.sessionmaker() as db:
        boss = (
            await db.execute(select(Agent).where(Agent.agent_type == "orchestrator"))
        ).scalar_one()
        return boss


def plan_limit(monkeypatch: pytest.MonkeyPatch, limit: int) -> None:
    """ORCHESTRATOR_MAX_TASKS_AT_ONCE for this test (the executor re-reads the settings)."""
    monkeypatch.setattr(waiting, "_max_plans", limit)
    monkeypatch.setattr(waiting, "configure", lambda settings: None)


async def run_one(app: FastAPI, queue: RecordingQueue, task_id: str) -> None:
    """Run exactly this task's job (the others stay in the queue)."""
    queue.enqueued.remove(uuid.UUID(task_id))
    await executor_for(app).execute(uuid.UUID(task_id))


async def parts_of(app: FastAPI, task_id: str) -> list[Task]:
    async with app.state.db.sessionmaker() as db:
        rows = await db.execute(select(Task).where(Task.parent_task_id == uuid.UUID(task_id)))
        return list(rows.scalars())


async def test_tasks_for_a_busy_agent_wait_in_line_and_start_in_order(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        agent = await create_agent(client, name="Writer")
        ids = []
        for title in ("One", "Two", "Three"):
            resp = await run_agent(client, agent["id"], title)
            assert resp.status_code == 200, resp.text
            ids.append(resp.json()["task"]["id"])
        waiting_ones = [await task_of(app, i) for i in ids[1:]]
        assert [(t.status, t.status_reason) for t in waiting_ones] == [
            ("created", "waiting_for_agent"),
            ("created", "waiting_for_agent"),
        ]
        await drain(app, queue)
    done = [await task_of(app, i) for i in ids]
    assert [t.status for t in done] == ["completed", "completed", "completed"]
    started = [t.started_at for t in done if t.started_at is not None]
    assert len(started) == 3 and started == sorted(started)  # in the order they were given


async def test_cancelling_the_running_task_starts_the_next_one_at_once(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        agent = await create_agent(client, name="Writer")
        first = (await run_agent(client, agent["id"], "One")).json()["task"]["id"]
        second = (await run_agent(client, agent["id"], "Two")).json()["task"]["id"]
        resp = await client.post(
            f"/api/v1/tasks/{first}/cancel", headers=await csrf_headers(client)
        )
        assert resp.status_code == 200
    nxt = await task_of(app, second)
    assert nxt.status == "queued" and nxt.run_id is not None  # not waiting for the sweep


async def test_the_orchestrator_runs_several_plans_at_once(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        a = await start_run(client, "Plan A", "[[mock:plan:2]]")
        await run_one(app, queue, a["task"]["id"])  # it plans; its parts go to the agents
        boss = await orchestrator(app)
        assert boss.status == "idle" and boss.current_task_id is None  # free meanwhile
        assert (await task_of(app, a["task"]["id"])).status == "waiting"
        b = await start_run(client, "Plan B", "[[mock:plan:2]]")
        assert b["run"] is not None  # taken at once, not after plan A
        await drain(app, queue)
    for started in (a, b):
        done = await task_of(app, started["task"]["id"])
        assert done.status == "completed", done.status_reason
        assert (done.result or "").startswith("Final answer combining")
        assert [p.status for p in await parts_of(app, started["task"]["id"])] == [
            "completed",
            "completed",
        ]


async def test_finished_parts_wait_while_the_orchestrator_plans_another_task(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        a = await start_run(client, "Plan A", "[[mock:plan:2]]")
        await run_one(app, queue, a["task"]["id"])
        b = await start_run(client, "Plan B", "Just answer")  # the Orchestrator is now busy
        for part in await parts_of(app, a["task"]["id"]):
            await run_one(app, queue, str(part.id))
        plan_a = await task_of(app, a["task"]["id"])
        assert (plan_a.status, plan_a.status_reason) == ("waiting", "parts_done")
        await drain(app, queue)  # B is answered, then A is merged
    assert (await task_of(app, b["task"]["id"])).status == "completed"
    merged = await task_of(app, a["task"]["id"])
    assert merged.status == "completed" and (merged.result or "").startswith("Final answer")
    boss = await orchestrator(app)
    assert boss.status == "idle" and boss.current_task_id is None


async def test_more_plans_than_the_limit_wait_in_line(
    app: FastAPI, owner: User, queue: RecordingQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_limit(monkeypatch, 1)
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        a = await start_run(client, "Plan A", "[[mock:plan:2]]")
        await run_one(app, queue, a["task"]["id"])
        b = await start_run(client, "Plan B", "Just answer")
        assert b["run"] is None
        assert (await task_of(app, b["task"]["id"])).status_reason == "waiting_for_agent"
        await drain(app, queue)
    assert (await task_of(app, a["task"]["id"])).status == "completed"
    assert (await task_of(app, b["task"]["id"])).status == "completed"


async def test_a_chat_hand_off_in_line_links_to_its_run_once_it_starts(
    app: FastAPI, owner: User, queue: RecordingQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_limit(monkeypatch, 1)
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        await start_run(client, "Plan A", "Just answer")  # the Orchestrator is reserved
        chat = (
            await client.post("/api/v1/chats", json={}, headers=await csrf_headers(client))
        ).json()
        resp = await client.post(
            f"/api/v1/chats/{chat['id']}/handoff",
            json={"content": "Compare two laptops"},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["run"] is None
        await drain(app, queue)
        page = (await client.get(f"/api/v1/chats/{chat['id']}/messages")).json()
    task = await task_of(app, resp.json()["task"]["id"])
    assert task.status == "completed" and task.run_id is not None
    question, answer = page["items"]
    assert question["agent_run_id"] == str(task.run_id)
    assert answer["agent_run_id"] == str(task.run_id) and answer["role"] == "assistant"
    async with app.state.db.sessionmaker() as db:
        assert (await db.get(Message, uuid.UUID(question["id"]))) is not None
