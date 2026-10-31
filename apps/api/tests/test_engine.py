"""Agent engine: runs execute in the background (executor = what the ARQ job calls)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update

from app.models import Agent, AgentEvent, AgentRun, Task, User
from app.providers import mock_provider
from app.providers.base import ChatRequest, ChatResult, ToolCall
from app.workers.recovery import recover, sweep_queued
from tests.conftest import (
    RecordingQueue,
    add_mock_model,
    create_agent,
    csrf_headers,
    executor_for,
    logged_in_client,
    run_agent,
)


async def row(app: FastAPI, model: Any, id_: Any) -> Any:
    async with app.state.db.sessionmaker() as db:
        return await db.get(model, uuid.UUID(str(id_)))


async def event_types(app: FastAPI, task_id: str) -> list[str]:
    async with app.state.db.sessionmaker() as db:
        rows = await db.execute(
            select(AgentEvent)
            .where(AgentEvent.task_id == uuid.UUID(task_id))
            .order_by(AgentEvent.seq)
        )
        return [e.type for e in rows.scalars()]


async def agent_statuses(app: FastAPI, agent_id: str) -> list[str]:
    async with app.state.db.sessionmaker() as db:
        rows = await db.execute(
            select(AgentEvent)
            .where(
                AgentEvent.agent_id == uuid.UUID(agent_id),
                AgentEvent.type == "agent.status_changed",
            )
            .order_by(AgentEvent.seq)
        )
        return [e.payload["new_status"] for e in rows.scalars()]


class SlowGateway:
    """Wraps the real gateway; complete() takes ``delay`` seconds."""

    def __init__(self, inner: Any, delay: float) -> None:
        self.inner = inner
        self.delay = delay
        self.calls = 0

    async def resolve(self, *a: Any, **k: Any) -> Any:
        return await self.inner.resolve(*a, **k)

    async def complete(self, target: Any, req: ChatRequest) -> ChatResult:
        self.calls += 1
        await asyncio.sleep(self.delay)
        return ChatResult(text=f"slow answer {self.calls}")


async def setup_agent(client: httpx.AsyncClient, **agent: Any) -> dict[str, Any]:
    await add_mock_model(client)
    return await create_agent(client, **agent)


async def test_agent_runs_task_in_background_and_returns_to_idle(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        agent = await setup_agent(client)
        resp = await run_agent(client, agent["id"], "Summarise", "Say hi")
        assert resp.status_code == 200, resp.text
        started = resp.json()
        task_id = started["task"]["id"]
        assert started["task"]["status"] == "queued"
        assert queue.enqueued == [uuid.UUID(task_id)]

        # The worker picks it up — no browser involved.
        await executor_for(app).execute(uuid.UUID(task_id))

        detail = (await client.get(f"/api/v1/tasks/{task_id}")).json()
        assert detail["task"]["status"] == "completed"
        assert detail["task"]["result"].startswith("Echo: # Task: Summarise")
        assert detail["run"]["status"] == "completed"
        assert detail["run"]["steps"] == 1
        assert detail["run"]["usage"]["output_tokens"] > 0
        agent_now = (await client.get(f"/api/v1/agents/{agent['id']}")).json()
        assert agent_now["status"] == "idle" and agent_now["current_task_id"] is None

    assert await agent_statuses(app, agent["id"]) == [
        "planning",
        "working",
        "reviewing",
        "completed",
        "idle",
    ]
    types = await event_types(app, task_id)
    for expected in (
        "task.created",
        "task.updated",
        "agent.task_started",
        "agent.message",
        "task.completed",
        "agent.task_completed",
    ):
        assert expected in types


async def test_busy_agent_rejects_a_second_task(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        agent = await setup_agent(client)
        assert (await run_agent(client, agent["id"], "One")).status_code == 200
        second = await run_agent(client, agent["id"], "Two")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "agent_busy"


async def test_provider_error_fails_the_task_honestly(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        agent = await setup_agent(client)
        task_id = (
            await run_agent(client, agent["id"], "Boom", "[[mock:error:auth_failed]]")
        ).json()["task"]["id"]
        await executor_for(app).execute(uuid.UUID(task_id))
        task = (await client.get(f"/api/v1/tasks/{task_id}")).json()["task"]
        assert task["status"] == "failed"
        assert task["error_code"] == "provider_auth_failed"
        assert task["error_id"] and task["result"] is None
        assert (await client.get(f"/api/v1/agents/{agent['id']}")).json()["status"] == "failed"

        # The next task starts cleanly from idle.
        task2 = (await run_agent(client, agent["id"], "Again")).json()["task"]["id"]
        await executor_for(app).execute(uuid.UUID(task2))
        assert (await client.get(f"/api/v1/tasks/{task2}")).json()["task"]["status"] == "completed"
    assert "agent.task_failed" in await event_types(app, task_id)


async def test_missing_model_fails_with_clear_code(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        agent = await create_agent(client)  # no provider at all
        task_id = (await run_agent(client, agent["id"], "No model")).json()["task"]["id"]
        await executor_for(app).execute(uuid.UUID(task_id))
        task = (await client.get(f"/api/v1/tasks/{task_id}")).json()["task"]
    assert (task["status"], task["error_code"]) == ("failed", "no_model_configured")


async def test_max_steps_limit_is_enforced_in_code(
    app: FastAPI, owner: User, queue: RecordingQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    def always_call_tools(req: ChatRequest) -> ChatResult | None:
        return ChatResult(text="", tool_calls=(ToolCall("c1", "loop_forever", {}),))

    monkeypatch.setattr(mock_provider, "_handlers", [always_call_tools])
    async with logged_in_client(app) as client:
        agent = await setup_agent(client, limits={"max_steps": 3})
        task_id = (await run_agent(client, agent["id"], "Loop")).json()["task"]["id"]
        await executor_for(app).execute(uuid.UUID(task_id))
        detail = (await client.get(f"/api/v1/tasks/{task_id}")).json()
    assert detail["task"]["error_code"] == "max_steps_exceeded"
    assert detail["run"]["steps"] == 3


async def test_agent_limit_cannot_exceed_global_limit(
    app_factory: Any, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        mock_provider,
        "_handlers",
        [lambda req: ChatResult(text="", tool_calls=(ToolCall("c", "x", {}),))],
    )
    app = await app_factory(max_steps_per_run=2)
    app.state.queue = RecordingQueue()
    async with logged_in_client(app) as client:
        agent = await setup_agent(client, limits={"max_steps": 500})
        task_id = (await run_agent(client, agent["id"], "Loop")).json()["task"]["id"]
        await executor_for(app).execute(uuid.UUID(task_id))
        assert (await client.get(f"/api/v1/tasks/{task_id}")).json()["run"]["steps"] == 2


async def test_run_timeout(app: FastAPI, owner: User, queue: RecordingQueue) -> None:
    async with logged_in_client(app) as client:
        agent = await setup_agent(client)
        started = (await run_agent(client, agent["id"], "Slow")).json()
    # Pretend the run already used almost all of its time.
    async with app.state.db.sessionmaker() as db:
        await db.execute(
            update(AgentRun)
            .where(AgentRun.id == uuid.UUID(started["run"]["id"]))
            .values(state={"elapsed_seconds": app.state.settings.run_timeout_seconds - 0.3})
        )
        await db.commit()
    executor = executor_for(app)
    executor.gateway = SlowGateway(app.state.gateway, delay=2.0)
    await executor.execute(uuid.UUID(started["task"]["id"]))
    task = await row(app, Task, started["task"]["id"])
    assert (task.status, task.error_code) == ("failed", "run_timeout")


async def test_cancel_stops_a_running_agent(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        agent = await setup_agent(client)
        task_id = (await run_agent(client, agent["id"], "Long")).json()["task"]["id"]
        executor = executor_for(app)
        slow = SlowGateway(app.state.gateway, delay=30)
        executor.gateway = slow
        running = asyncio.create_task(executor.execute(uuid.UUID(task_id)))
        await asyncio.sleep(0.4)
        resp = await client.post(
            f"/api/v1/tasks/{task_id}/cancel", headers=await csrf_headers(client)
        )
        assert resp.status_code == 200 and resp.json()["status"] == "cancelled"
        await asyncio.wait_for(running, timeout=3)  # abandons the in-flight model call
        task = (await client.get(f"/api/v1/tasks/{task_id}")).json()["task"]
        agent_now = (await client.get(f"/api/v1/agents/{agent['id']}")).json()
    assert task["status"] == "cancelled" and task["result"] is None
    assert agent_now["status"] == "idle"
    assert "task.completed" not in await event_types(app, task_id)


async def test_pause_and_resume_continue_from_checkpoint(
    app: FastAPI, owner: User, queue: RecordingQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    def two_steps(req: ChatRequest) -> ChatResult | None:
        calls["n"] += 1
        if calls["n"] == 1:
            return ChatResult(text="thinking", tool_calls=(ToolCall("c1", "noop", {}),))
        return None  # echo → final

    monkeypatch.setattr(mock_provider, "_handlers", [two_steps])
    async with logged_in_client(app) as client:
        agent = await setup_agent(client)
        task_id = (await run_agent(client, agent["id"], "Pausable")).json()["task"]["id"]
        executor = executor_for(app)
        executor.gateway = SlowGateway(app.state.gateway, delay=30)
        running = asyncio.create_task(executor.execute(uuid.UUID(task_id)))
        await asyncio.sleep(0.4)
        resp = await client.post(
            f"/api/v1/agents/{agent['id']}/pause", headers=await csrf_headers(client)
        )
        assert resp.status_code == 200 and resp.json()["status"] == "paused"
        await asyncio.wait_for(running, timeout=3)
        task = (await client.get(f"/api/v1/tasks/{task_id}")).json()["task"]
        assert (task["status"], task["status_reason"]) == ("waiting", "paused")

        resp = await client.post(
            f"/api/v1/agents/{agent['id']}/resume", headers=await csrf_headers(client)
        )
        assert resp.status_code == 200 and resp.json()["status"] == "working"
        assert (await client.get(f"/api/v1/tasks/{task_id}")).json()["task"]["status"] == "queued"
        assert queue.enqueued[-1] == uuid.UUID(task_id)
        await executor_for(app).execute(uuid.UUID(task_id))
        detail = (await client.get(f"/api/v1/tasks/{task_id}")).json()
    assert detail["task"]["status"] == "completed"
    assert detail["run"]["steps"] == 2  # the first step was not lost


async def test_duplicate_jobs_run_the_task_once(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        agent = await setup_agent(client)
        task_id = uuid.UUID((await run_agent(client, agent["id"], "Once")).json()["task"]["id"])
    executor = executor_for(app)
    await asyncio.gather(executor.execute(task_id), executor.execute(task_id))
    types = await event_types(app, str(task_id))
    assert types.count("agent.task_started") == 1
    assert types.count("task.completed") == 1


async def test_worker_shutdown_requeues_the_task(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        agent = await setup_agent(client)
        task_id = (await run_agent(client, agent["id"], "Interrupted")).json()["task"]["id"]
    executor = executor_for(app)
    executor.gateway = SlowGateway(app.state.gateway, delay=30)
    running = asyncio.create_task(executor.execute(uuid.UUID(task_id)))
    await asyncio.sleep(0.3)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    task = await row(app, Task, task_id)
    assert (task.status, task.status_reason) == ("queued", "worker_shutdown")


async def test_recovery_resumes_safe_runs_and_parks_unknown_outcomes(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        safe_agent = await setup_agent(client, name="Safe")
        risky_agent = await create_agent(client, name="Risky")
        safe = (await run_agent(client, safe_agent["id"], "Safe")).json()
        risky = (await run_agent(client, risky_agent["id"], "Risky")).json()
    # Simulate a crash mid-run: both tasks are "running"; one had a side effect in flight.
    async with app.state.db.sessionmaker() as db:
        await db.execute(
            update(Task)
            .where(Task.id.in_([uuid.UUID(safe["task"]["id"]), uuid.UUID(risky["task"]["id"])]))
            .values(status="running")
        )
        await db.execute(update(Agent).values(status="working"))
        await db.execute(
            update(AgentRun)
            .where(AgentRun.id == uuid.UUID(risky["run"]["id"]))
            .values(
                state={
                    "in_flight": {
                        "operation_id": "op-1",
                        "tool": "github_create_pr",
                        "side_effects": True,
                    }
                }
            )
        )
        await db.commit()
    fresh_queue = RecordingQueue()
    stats = await recover(app.state.db.sessionmaker, fresh_queue)
    assert stats["resumed"] == 1 and stats["needs_decision"] == 1
    assert fresh_queue.enqueued == [uuid.UUID(safe["task"]["id"])]
    risky_task = await row(app, Task, risky["task"]["id"])
    assert (risky_task.status, risky_task.status_reason) == ("waiting", "unknown_outcome")
    assert (await row(app, Agent, risky_agent["id"])).status == "waiting"
    # The safe one completes after the "restart".
    await executor_for(app).execute(uuid.UUID(safe["task"]["id"]))
    assert (await row(app, Task, safe["task"]["id"])).status == "completed"


async def test_sweeper_requeues_stale_queued_tasks(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        agent = await setup_agent(client)
        task_id = (await run_agent(client, agent["id"], "Lost enqueue")).json()["task"]["id"]
    sweeper_queue = RecordingQueue()
    assert (
        await sweep_queued(app.state.db.sessionmaker, sweeper_queue, older_than_seconds=3600) == 0
    )
    assert await sweep_queued(app.state.db.sessionmaker, sweeper_queue, older_than_seconds=-1) == 1
    assert sweeper_queue.enqueued == [uuid.UUID(task_id)]


async def test_kill_switch_stops_everything_and_blocks_new_runs(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        a1 = await setup_agent(client, name="A1")
        a2 = await create_agent(client, name="A2")
        t1 = (await run_agent(client, a1["id"], "T1")).json()["task"]["id"]
        t2 = (await run_agent(client, a2["id"], "T2")).json()["task"]["id"]
        resp = await client.post("/api/v1/system/stop-all", headers=await csrf_headers(client))
        assert resp.json() == {"cancelled_tasks": 2}
        for tid in (t1, t2):
            assert (await client.get(f"/api/v1/tasks/{tid}")).json()["task"][
                "status"
            ] == "cancelled"
        blocked = await run_agent(client, a1["id"], "Blocked")
        assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "engine_stopped"
        assert (await client.get("/api/v1/system/state")).json()["engine_stopped"] is True
        await client.post("/api/v1/system/start", headers=await csrf_headers(client))
        assert (await run_agent(client, a1["id"], "Allowed")).status_code == 200


async def test_idempotency_key_prevents_duplicate_runs(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        agent = await setup_agent(client)
        first = await run_agent(client, agent["id"], "Once", **{"Idempotency-Key": "abc-1"})
        again = await run_agent(client, agent["id"], "Once", **{"Idempotency-Key": "abc-1"})
        assert first.status_code == again.status_code == 200
        assert first.json()["task"]["id"] == again.json()["task"]["id"]
        other = await run_agent(client, agent["id"], "Different", **{"Idempotency-Key": "abc-1"})
        assert (
            other.status_code == 422 and other.json()["error"]["code"] == "idempotency_key_reused"
        )
        tasks = (await client.get("/api/v1/tasks")).json()["items"]
    assert len(tasks) == 1
    assert len(queue.enqueued) == 1
