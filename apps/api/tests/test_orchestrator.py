"""The Orchestrator (Sprint 4; no temporary subagents since 2026-11-02): it plans, gives
every part to one of the owner's persistent agents — creating a new agent when none fits —
and merges the results. Plans come from the scripted mock provider."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.models import Agent, AgentEvent, AgentMessage, AuditLog, Task, User
from app.orchestrator.messaging import DeliveryRefused, send_message
from app.orchestrator.parts import create_agent as orchestrator_creates
from app.orchestrator.plan import NewAgentSpec, PlanError, parse_plan
from tests.conftest import (
    AppFactory,
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
    return resp.json()


async def tree(client: httpx.AsyncClient, run_id: str) -> dict[str, Any]:
    resp = await client.get(f"/api/v1/runs/{run_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def max_concurrent_active(app: FastAPI, root_task_id: str) -> int:
    """Replay the ordered event log and compute the peak of queued+running subtasks."""
    async with app.state.db.sessionmaker() as db:
        subtask_ids = {
            str(t)
            for t in (
                await db.execute(
                    select(Task.id).where(Task.parent_task_id == uuid.UUID(root_task_id))
                )
            ).scalars()
        }
        events = (
            await db.execute(
                select(AgentEvent).where(AgentEvent.type.like("task.%")).order_by(AgentEvent.seq)
            )
        ).scalars()
        status: dict[str, str] = {}
        peak = 0
        for e in events:
            task = e.payload.get("task")
            if task and task["id"] in subtask_ids:
                status[task["id"]] = task["status"]
                peak = max(peak, sum(1 for s in status.values() if s in ("queued", "running")))
    return peak


async def test_simple_request_is_answered_directly(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        started = await start_run(client, "What is 2+2?")
        await drain(app, queue)
        t = await tree(client, started["run"]["id"])
    assert t["task"]["status"] == "completed"
    assert t["task"]["result"] == "Direct answer: # Task: What is 2+2?"
    assert t["run"]["plan"]["mode"] == "direct"
    assert t["team"] == [] and t["subtasks"] == []


async def test_complex_task_is_split_executed_and_merged(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        started = await start_run(client, "Market report", "[[mock:plan:3]]")
        await drain(app, queue)
        t = await tree(client, started["run"]["id"])
        orchestrator = next(
            a
            for a in (await client.get("/api/v1/agents")).json()
            if a["agent_type"] == "orchestrator"
        )
    assert t["task"]["status"] == "completed", t["task"]
    assert [s["status"] for s in t["subtasks"]] == ["completed"] * 3
    assert t["task"]["result"].startswith("Final answer combining:")
    assert t["task"]["result"].count("(task_result)") == 3
    assert t["task"]["progress"] == 100
    # No agent fitted: the Orchestrator created two persistent agents; they stay in the office
    team = {a["name"]: a for a in t["team"]}
    assert set(team) == {"Researcher", "Analyst"}
    assert all(a["agent_type"] == "autonomous" and a["archived_at"] is None for a in team.values())
    assert all(a["model_config_id"] == orchestrator["model_config_id"] for a in team.values())
    assert all(a["autonomy_level"] == orchestrator["autonomy_level"] for a in team.values())
    results = [m for m in t["messages"] if m["message_type"] == "task_result"]
    assert len(results) == 3 and all(m["receiver_agent_id"] == orchestrator["id"] for m in results)
    assert orchestrator["status"] == "idle"
    async with app.state.db.sessionmaker() as db:
        created = (
            (
                await db.execute(
                    select(AuditLog).where(
                        AuditLog.action == "agent.created", AuditLog.actor_type == "agent"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert {a.details["name"] for a in created} == {"Researcher", "Analyst"}
    assert all(a.details["created_by"] == "orchestrator" for a in created)


async def test_the_next_plan_reuses_the_agents_it_created(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        await start_run(client, "First", "[[mock:plan:2]]")
        await drain(app, queue)
        second = await start_run(client, "Second", "[[mock:plan:2]]")
        await drain(app, queue)
        t = await tree(client, second["run"]["id"])
        agents = (await client.get("/api/v1/agents")).json()
    assert t["task"]["status"] == "completed"
    names = [a["name"] for a in agents if a["agent_type"] == "autonomous"]
    assert sorted(names) == ["Analyst", "Researcher"]  # no twins


async def test_active_parts_limit_is_enforced_under_parallel_completion(
    app_factory: AppFactory, owner: User
) -> None:
    app = await app_factory(
        max_active_parts_per_run=5, max_subtasks_per_plan=8, orchestrator_max_new_agents=8
    )
    queue = RecordingQueue()
    app.state.queue = queue
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        started = await start_run(client, "Big job", "[[mock:plan:8]] [[mock:spread]]")
        await drain(app, queue, parallel=True)
        t = await tree(client, started["run"]["id"])
    assert t["task"]["status"] == "completed"
    assert len(t["subtasks"]) == 8
    peak = await max_concurrent_active(app, started["task"]["id"])
    assert peak == 5  # parallel up to the limit, never above it


async def test_limit_of_two_active(app_factory: AppFactory, owner: User) -> None:
    app = await app_factory(max_active_parts_per_run=2, orchestrator_max_new_agents=4)
    queue = RecordingQueue()
    app.state.queue = queue
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        started = await start_run(client, "Job", "[[mock:plan:4]] [[mock:spread]]")
        await drain(app, queue, parallel=True)
    assert await max_concurrent_active(app, started["task"]["id"]) == 2


async def test_dependencies_run_in_order_and_pass_results(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        started = await start_run(client, "Chain", "[[mock:plan:3]] [[mock:chain]]")
        await drain(app, queue, parallel=True)
        t = await tree(client, started["run"]["id"])
    subtasks = {s["extra"]["key"]: s for s in t["subtasks"]}
    assert all(s["status"] == "completed" for s in subtasks.values())
    assert subtasks["part-1"]["completed_at"] <= subtasks["part-2"]["started_at"]
    assert subtasks["part-2"]["completed_at"] <= subtasks["part-3"]["started_at"]
    # part-1's result was passed to part-2 as an input, fenced as data
    assert '<input from="Researcher" type="task_result">' in subtasks["part-2"]["description"]


async def test_failed_dependency_cancels_dependants_and_run_fails_honestly(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        started = await start_run(
            client, "Fragile", "[[mock:plan:2]] [[mock:chain]] [[mock:failpart:1]]"
        )
        await drain(app, queue)
        t = await tree(client, started["run"]["id"])
    subtasks = {s["extra"]["key"]: s for s in t["subtasks"]}
    assert subtasks["part-1"]["status"] == "failed"
    assert (subtasks["part-2"]["status"], subtasks["part-2"]["status_reason"]) == (
        "cancelled",
        "dependency_failed",
    )
    assert (t["task"]["status"], t["task"]["error_code"]) == ("failed", "subtasks_failed")


async def test_partial_failure_still_merges_what_succeeded(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        started = await start_run(client, "Mostly fine", "[[mock:plan:3]] [[mock:failpart:2]]")
        await drain(app, queue)
        t = await tree(client, started["run"]["id"])
    assert t["task"]["status"] == "completed"
    assert t["task"]["result"].count("(task_result)") == 2
    assert t["task"]["result"].count("(error)") == 1  # the gap is reported, not hidden


async def test_review_is_done_by_the_orchestrator_itself(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        started = await start_run(client, "Reviewed", "[[mock:plan:2]] [[mock:review]]")
        await drain(app, queue)
        t = await tree(client, started["run"]["id"])
    assert t["task"]["status"] == "completed"
    assert not [s for s in t["subtasks"] if s["task_type"] == "review"]  # no reviewer agent
    assert t["task"]["result"].endswith("(checked)")


async def test_a_plan_may_create_only_a_few_agents(app_factory: AppFactory, owner: User) -> None:
    app = await app_factory(orchestrator_max_new_agents=1)
    queue = RecordingQueue()
    app.state.queue = queue
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        started = await start_run(client, "Two new ones", "[[mock:plan:2]]")
        await drain(app, queue)
        t = await tree(client, started["run"]["id"])
        agents = (await client.get("/api/v1/agents")).json()
    assert (t["task"]["status"], t["task"]["error_code"]) == ("failed", "invalid_plan")
    assert [a for a in agents if a["agent_type"] == "autonomous"] == []


async def test_plan_with_too_many_subtasks_is_rejected(
    app_factory: AppFactory, owner: User
) -> None:
    app = await app_factory(max_subtasks_per_plan=3)
    queue = RecordingQueue()
    app.state.queue = queue
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        started = await start_run(client, "Too many", "[[mock:plan:5]]")
        await drain(app, queue)
        t = await tree(client, started["run"]["id"])
    assert (t["task"]["status"], t["task"]["error_code"]) == ("failed", "invalid_plan")
    assert t["team"] == []


async def test_invalid_plan_is_retried_once(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        started = await start_run(client, "Retry", "[[mock:badplan]]")
        await drain(app, queue)
        t = await tree(client, started["run"]["id"])
        t2 = await tree(
            client, (await start_run(client, "Never valid", "[[mock:alwaysbad]]"))["run"]["id"]
        )
        await drain(app, queue)
        t2 = await tree(client, t2["run"]["id"])
    assert t["task"]["status"] == "completed" and t["run"]["steps"] == 2
    assert (t2["task"]["status"], t2["task"]["error_code"]) == ("failed", "invalid_plan")


def test_plan_validation_rejects_cycles_and_unknown_deps() -> None:
    def plan(*parts: dict[str, Any]) -> str:
        return json.dumps({"mode": "delegate", "subtasks": list(parts)})

    def part(key: str, *deps: str, agent: str = "W") -> dict[str, Any]:
        return {"key": key, "title": key.upper(), "agent": agent, "depends_on": list(deps)}

    bad = [
        plan(part("a", "b"), part("b", "a")),
        plan(part("a", "zzz")),
        plan(part("a"), part("a")),
        plan(),
        '{"mode":"direct","answer":""}',
        plan(part("a", agent="")),  # nobody does it
        "no json here",
    ]
    for text in bad:
        with pytest.raises(PlanError):
            parse_plan(text, max_subtasks=8, agents=["W"])
    direct, _ = parse_plan('Sure! ```json\n{"mode":"direct","answer":"hi"}\n```', max_subtasks=8)
    assert direct.answer == "hi"


async def test_new_agents_never_get_more_than_the_orchestrator(app: FastAPI, owner: User) -> None:
    async with app.state.db.sessionmaker() as db:
        parent = Agent(
            user_id=owner.id,
            name="o",
            agent_type="orchestrator",
            depth=0,
            allowed_tools=["fs_read"],
            autonomy_level="supervised",
            permissions={
                "tools": {"fs_read": "approve"},
                "always": [{"id": "x", "tool": "fs_read"}],
            },
            limits={"max_steps": 7},
            memory_settings={},
            status="idle",
        )
        db.add(parent)
        task = Task(
            user_id=owner.id,
            title="t",
            description="",
            task_type="user",
            status="running",
            depends_on=[],
            extra={},
        )
        db.add(task)
        await db.flush()
        spec = NewAgentSpec(name="Helper", tools=["fs_read", "terminal_run", "github_write_file"])
        agent = await orchestrator_creates(db, orchestrator=parent, spec=spec, task=task)
    assert agent.agent_type == "autonomous" and agent.allowed_tools == ["fs_read"]
    assert agent.autonomy_level == "supervised" and agent.limits == {"max_steps": 7}
    assert agent.permissions == {"tools": {"fs_read": "approve"}}  # never its standing approvals
    assert agent.full_access is False


def test_new_agent_tools_are_limited_to_the_orchestrators_in_the_plan() -> None:
    text = json.dumps(
        {
            "mode": "delegate",
            "new_agents": [{"name": "Coder", "tools": ["fs_write", "github_write_file"]}],
            "subtasks": [{"key": "a", "title": "A", "agent": "coder"}],
        }
    )
    plan, warnings = parse_plan(text, max_subtasks=8, max_new_agents=1, tools=["fs_write"])
    assert plan.new_agents[0].tools == ["fs_write"] and plan.subtasks[0].agent == "Coder"
    assert any("github_write_file" in w for w in warnings)
    # an existing agent of that name is used instead of a twin
    plan, warnings = parse_plan(text, max_subtasks=8, agents=["Coder"], max_new_agents=1)
    assert plan.new_agents == [] and plan.subtasks[0].agent == "Coder"
    with pytest.raises(PlanError, match="new agents"):
        parse_plan(text, max_subtasks=8, max_new_agents=0)


async def test_messages_between_different_runs_are_refused(app: FastAPI, owner: User) -> None:
    async with app.state.db.sessionmaker() as db:
        a = Agent(
            user_id=owner.id,
            name="a",
            agent_type="subagent",
            run_id=uuid.uuid4(),
            allowed_tools=[],
            permissions={},
            limits={},
            memory_settings={},
            status="idle",
        )
        b = Agent(
            user_id=owner.id,
            name="b",
            agent_type="subagent",
            run_id=uuid.uuid4(),
            allowed_tools=[],
            permissions={},
            limits={},
            memory_settings={},
            status="idle",
        )
        db.add_all([a, b])
        await db.flush()
        with pytest.raises(DeliveryRefused):
            await send_message(
                db,
                sender=a,
                receiver=b,
                message_type="task_result",
                summary="leak",
                result="secret",
            )
        await db.commit()
        stored = (await db.execute(select(AgentMessage))).scalar_one()
        audit = [x.action for x in (await db.execute(select(AuditLog))).scalars()]
    assert stored.status == "refused" and "result" not in stored.content
    assert "agent.message_refused" in audit


async def test_cancelling_the_run_stops_every_part(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        started = await start_run(client, "Cancel me", "[[mock:plan:4]]")
        # Run only the orchestrator's planning job: subtasks are created and queued.
        from tests.conftest import executor_for

        await executor_for(app).execute(queue.enqueued.pop(0))
        resp = await client.post(
            f"/api/v1/tasks/{started['task']['id']}/cancel", headers=await csrf_headers(client)
        )
        assert resp.status_code == 200
        await drain(app, queue)  # leftover jobs find their tasks cancelled and do nothing
        t = await tree(client, started["run"]["id"])
    assert t["task"]["status"] == "cancelled"
    assert {s["status"] for s in t["subtasks"]} == {"cancelled"}
    assert all(a["archived_at"] is None for a in t["team"])  # the agents stay in the office


async def test_chat_handoff_posts_the_result_back(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        chat = (
            await client.post("/api/v1/chats", json={}, headers=await csrf_headers(client))
        ).json()
        resp = await client.post(
            f"/api/v1/chats/{chat['id']}/handoff",
            json={"content": "Compare three laptops [[mock:plan:3]]"},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 200, resp.text
        run_id = resp.json()["run"]["id"]
        page = (await client.get(f"/api/v1/chats/{chat['id']}/messages")).json()
        assert [(m["role"], m["agent_run_id"]) for m in page["items"]] == [("user", run_id)]
        await drain(app, queue)
        page = (await client.get(f"/api/v1/chats/{chat['id']}/messages")).json()
    assert [m["role"] for m in page["items"]] == ["user", "assistant"]
    answer = page["items"][1]
    assert answer["agent_run_id"] == run_id and answer["status"] == "completed"
    assert answer["content"].startswith("Final answer combining:")


# --- persistent agents take parts of a plan (spec 14.1) --------------------------------------


def test_plan_can_name_only_the_owners_agents() -> None:
    text = json.dumps(
        {
            "mode": "delegate",
            "subtasks": [
                {"key": "a", "title": "A", "agent": "writer", "tools": ["x"], "delegate": True}
            ],
        }
    )
    plan, _ = parse_plan(text, max_subtasks=8, agents=["Writer"])
    assert plan.subtasks[0].agent == "Writer"  # canonical name; extra fields are ignored
    with pytest.raises(PlanError, match="must name the agent"):
        parse_plan(text, max_subtasks=8, agents=["Reviewer"])


async def test_orchestrator_gives_a_part_to_an_existing_agent_with_inputs(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        writer = await create_agent(client, name="Writer", specialization="texts")
        started = await start_run(
            client, "Report", "[[mock:plan:2]] [[mock:chain]] [[mock:assign:Writer]]"
        )
        await drain(app, queue)
        tree_resp = await tree(client, started["run"]["id"])
        writer_after = (await client.get(f"/api/v1/agents/{writer['id']}")).json()
    assert tree_resp["task"]["status"] == "completed"
    subtasks = {t["extra"]["key"]: t for t in tree_resp["subtasks"]}
    part2 = subtasks["part-2"]
    assert part2["agent_id"] == writer["id"] and part2["status"] == "completed"
    assert '<input from="' in part2["description"]  # the dependency's result was passed as data
    assert sorted(a["name"] for a in tree_resp["team"]) == ["Researcher", "Writer"]
    assert writer_after["archived_at"] is None and writer_after["status"] in ("idle", "completed")
    assert "Writer (task_result)" in tree_resp["run"]["result"]  # its result reached the merge
    async with app.state.db.sessionmaker() as db:
        refused = (
            (await db.execute(select(AuditLog).where(AuditLog.action == "agent.message_refused")))
            .scalars()
            .all()
        )
    assert refused == []


async def test_a_busy_agent_takes_its_part_when_it_is_free(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        writer = await create_agent(client, name="Writer")
        own = await run_agent(client, writer["id"], "Own job")  # reserves the agent (queued)
        assert own.status_code == 200
        started = await start_run(client, "Report", "[[mock:plan:2]] [[mock:assign:Writer]]")
        executor = executor_for(app)
        orchestrator_task = uuid.UUID(started["task"]["id"])
        queue.enqueued.remove(orchestrator_task)
        await executor.execute(orchestrator_task)  # plans while Writer is busy
        parts = (await tree(client, started["run"]["id"]))["subtasks"]
        assert {p["extra"]["key"]: p["status"] for p in parts}["part-2"] == "created"  # waits
        await drain(app, queue)  # Writer finishes its own job, then picks the part up
        final = await tree(client, started["run"]["id"])
    assert final["task"]["status"] == "completed"
    assert all(p["status"] == "completed" for p in final["subtasks"])
