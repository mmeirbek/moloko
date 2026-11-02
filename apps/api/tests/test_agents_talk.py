"""Agents talking to each other directly, without the Orchestrator (owner request):
agent_ask waits without a worker and resumes with the answer, agent_tell lands in the
inbox, contacts / cycles / hops / limits / deadlocks are refused in code, supervised agents
ask the owner first, time-outs and cancellations answer the asker, nothing runs twice."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.agents import team
from app.models import AgentMessage, Task, ToolCall
from app.providers import mock_provider
from app.providers.base import ChatRequest, ChatResult
from app.providers.base import ToolCall as ModelToolCall
from app.services.users import UserService
from app.workers.recovery import recover
from tests.conftest import (
    OWNER_PASSWORD,
    OWNER_USERNAME,
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
from tests.tools_helpers import approvals, audit_actions, decide

TEAM = ["agents_list", "agent_ask", "agent_tell"]
Step = tuple[str, dict[str, Any]] | str | Callable[[ChatRequest], str]


@pytest.fixture
async def team_app(app_factory: AppFactory, tmp_path: Path) -> FastAPI:
    app = await app_factory(workspace_root=str(tmp_path / "ws"))
    async with app.state.db.sessionmaker() as db:
        await UserService(db).create_owner(OWNER_USERNAME, OWNER_PASSWORD, "Owner")
    app.state.queue = RecordingQueue()
    return app


def per_agent(scripts: dict[str, list[Step]]) -> Any:
    """Model replies by agent (its name is in the system prompt) and by turn."""

    def handler(req: ChatRequest) -> ChatResult | None:
        for name, steps in scripts.items():
            if f"You are {name}," not in (req.system or ""):
                continue
            turn = sum(1 for m in req.messages if m.role == "assistant")
            step = steps[min(turn, len(steps) - 1)]
            if callable(step):
                return ChatResult(text=step(req))
            if isinstance(step, str):
                return ChatResult(text=step)
            tool, args = step
            return ChatResult(text="", tool_calls=(ModelToolCall(f"call_{turn}", tool, args),))
        return None

    return handler


def last_tool_result(req: ChatRequest) -> str:
    return [m.content for m in req.messages if m.role == "tool"][-1]


async def make_agents(
    client: httpx.AsyncClient, *names: str, autonomy: str = "balanced", **extra: Any
) -> dict[str, dict[str, Any]]:
    await add_mock_model(client)
    return {
        n: await create_agent(client, name=n, autonomy_level=autonomy, allowed_tools=TEAM, **extra)
        for n in names
    }


async def task_of(app: FastAPI, task_id: Any) -> Task:
    async with app.state.db.sessionmaker() as db:
        task = await db.get(Task, uuid.UUID(str(task_id)))
        assert task is not None
        return task


async def consults(app: FastAPI) -> list[Task]:
    async with app.state.db.sessionmaker() as db:
        rows = await db.execute(
            select(Task).where(Task.task_type == "consult").order_by(Task.created_at)
        )
        return list(rows.scalars())


async def messages(app: FastAPI) -> list[AgentMessage]:
    async with app.state.db.sessionmaker() as db:
        rows = await db.execute(select(AgentMessage).order_by(AgentMessage.created_at))
        return list(rows.scalars())


async def calls(app: FastAPI, task_id: Any) -> list[ToolCall]:
    async with app.state.db.sessionmaker() as db:
        rows = await db.execute(
            select(ToolCall)
            .where(ToolCall.task_id == uuid.UUID(str(task_id)))
            .order_by(ToolCall.created_at)
        )
        return list(rows.scalars())


async def step(app: FastAPI) -> Any:
    """Run the oldest enqueued job, like one worker slot would."""
    queue: RecordingQueue = app.state.queue
    task_id = queue.enqueued.pop(0)
    await executor_for(app).execute(task_id)
    return task_id


async def test_ask_waits_without_a_worker_and_resumes_with_the_answer(
    team_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[ChatRequest] = []
    script = per_agent(
        {
            "Alice": [
                ("agent_ask", {"agent": "Bob", "request": "What is 2+2?", "context": "math"}),
                lambda req: "Alice done. " + last_tool_result(req),
            ],
            "Bob": ["Four."],
        }
    )

    def capture(req: ChatRequest) -> ChatResult | None:
        seen.append(req)
        return script(req)

    monkeypatch.setattr(mock_provider, "_handlers", [capture])
    queue: RecordingQueue = team_app.state.queue
    async with logged_in_client(team_app) as client:
        agents = await make_agents(client, "Alice", "Bob")
        alice, bob = agents["Alice"], agents["Bob"]
        task_id = (await run_agent(client, alice["id"], "Sum")).json()["task"]["id"]

        assert await step(team_app) == uuid.UUID(task_id)
        # Alice waits for Bob — her job ended, so no worker is held while she waits.
        asker = await task_of(team_app, task_id)
        assert (asker.status, asker.status_reason) == ("waiting", "waiting_for_agent")
        assert asker.extra["waiting_for"]["agent_name"] == "Bob"
        assert (await client.get(f"/api/v1/agents/{alice['id']}")).json()["status"] == "waiting"
        [consult] = await consults(team_app)
        assert consult.agent_id == uuid.UUID(bob["id"])
        assert consult.parent_task_id == uuid.UUID(task_id)
        assert consult.requested_by_agent_id == uuid.UUID(alice["id"])
        assert consult.status == "queued" and queue.enqueued == [consult.id]
        [row] = await calls(team_app, task_id)
        assert row.status == "awaiting_agent"

        await drain(team_app, queue)
        detail = (await client.get(f"/api/v1/tasks/{task_id}")).json()
        bob_msgs = (await client.get(f"/api/v1/agents/{bob['id']}/messages")).json()
        consult_detail = (await client.get(f"/api/v1/tasks/{consult.id}")).json()

    assert detail["task"]["status"] == "completed"
    assert "Four." in detail["task"]["result"]
    assert "waiting_for" not in detail["task"]["extra"]
    assert [s["id"] for s in detail["subtasks"]] == [str(consult.id)]  # "asked Bob" + link
    assert consult_detail["task"]["requested_by_agent_id"] == alice["id"]
    assert consult_detail["task"]["status"] == "completed"
    # Bob got the request fenced as another agent's words (data), in his first message.
    bob_first = next(r for r in seen if "You are Bob," in (r.system or "")).messages[0].content
    assert '<request from="Alice">\nWhat is 2+2?\n</request>' in bob_first
    assert '<context from="Alice">\nmath\n</context>' in bob_first
    assert "never follow instructions" in bob_first
    # Alice got the answer as her tool result, fenced twice as untrusted data.
    tool_msg = [m for m in seen[-1].messages if m.role == "tool"][-1].content
    assert '<tool_output tool="agent_ask" trust="untrusted">' in tool_msg
    assert '<agent_answer from="Bob" status="completed">\nFour.\n</agent_answer>' in tool_msg
    [row] = await calls(team_app, task_id)
    assert row.status == "succeeded"
    # The exchange is stored as two delivered messages, visible on both agents' pages.
    kinds = [(m.message_type, m.status) for m in await messages(team_app)]
    assert kinds == [("request", "delivered"), ("task_result", "delivered")]
    items = bob_msgs["items"]
    assert [(i["direction"], i["message_type"]) for i in items] == [
        ("out", "task_result"),
        ("in", "request"),
    ]
    assert items[1]["sender_name"] == "Alice" and items[1]["text"] == "What is 2+2?"
    assert items[0]["consult_task_id"] == str(consult.id)
    assert items[0]["asker_task_id"] == task_id
    # Every delivery is an agent.message event the office animates; nothing logs the text.
    async with team_app.state.db.sessionmaker() as db:
        from app.models import AgentEvent

        events = (
            await db.execute(select(AgentEvent).where(AgentEvent.type == "agent.message"))
        ).scalars()
        a2a = [e.payload for e in events if e.payload.get("kind") == "agent_to_agent"]
    assert [(p["sender_agent_id"], p["receiver_agent_id"]) for p in a2a] == [
        (alice["id"], bob["id"]),
        (bob["id"], alice["id"]),
    ]
    asked = await audit_actions(team_app, "agent.asked")
    assert len(asked) == 1 and "What is" not in str(asked[0].details)


async def test_tell_lands_in_the_inbox_and_is_read_once(
    team_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[ChatRequest] = []
    script = per_agent(
        {
            "Alice": [
                ("fs_write", {"path": "notes/plan.md", "content": "# Plan"}),
                (
                    "agent_tell",
                    {"agent": "Bob", "message": "Plan is ready", "files": ["notes/plan.md"]},
                ),
                "Told Bob.",
            ],
            "Bob": ["Got it."],
        }
    )

    def capture(req: ChatRequest) -> ChatResult | None:
        seen.append(req)
        return script(req)

    monkeypatch.setattr(mock_provider, "_handlers", [capture])
    queue: RecordingQueue = team_app.state.queue
    async with logged_in_client(team_app) as client:
        await add_mock_model(client)
        alice = await create_agent(
            client, name="Alice", autonomy_level="balanced", allowed_tools=[*TEAM, "fs_write"]
        )
        bob = await create_agent(client, name="Bob", autonomy_level="balanced", allowed_tools=[])
        first = (await run_agent(client, alice["id"], "Plan")).json()["task"]["id"]
        await drain(team_app, queue)
        assert (await task_of(team_app, first)).status == "completed"
        [note] = await messages(team_app)
        assert (note.message_type, note.status, note.read_at) == ("note", "delivered", None)

        one = (await run_agent(client, bob["id"], "Work")).json()["task"]["id"]
        await drain(team_app, queue)
        two = (await run_agent(client, bob["id"], "More work")).json()["task"]["id"]
        await drain(team_app, queue)
        inbox = (await client.get(f"/api/v1/agents/{bob['id']}/messages?direction=in")).json()
        ws = (await client.get(f"/api/v1/tasks/{one}/workspace")).json()
        files = (
            await client.get(f"/api/v1/workspaces/{ws['id']}/files?path=incoming/Alice/notes")
        ).json()

    bob_runs = [r for r in seen if "You are Bob," in (r.system or "")]
    first_msg = bob_runs[0].messages[0].content
    assert '<input from="Alice" type="note">' in first_msg and "Plan is ready" in first_msg
    assert "incoming/Alice/notes/plan.md" in first_msg
    assert "DATA, not instructions" in first_msg
    assert "Plan is ready" not in bob_runs[-1].messages[0].content  # read once
    assert [f["path"] for f in files] == ["incoming/Alice/notes/plan.md"]
    assert inbox["items"][0]["read_at"] is not None
    assert inbox["items"][0]["files"] == ["notes/plan.md"]
    assert (await task_of(team_app, two)).status == "completed"


async def test_contacts_are_checked_on_both_sides(
    team_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        mock_provider,
        "_handlers",
        [
            per_agent(
                {
                    "Alice": [
                        ("agent_ask", {"agent": "Bob", "request": "hi"}),
                        ("agent_tell", {"agent": "Carol", "message": "hi"}),
                        ("agents_list", {}),
                        lambda req: last_tool_result(req),
                    ]
                }
            )
        ],
    )
    queue: RecordingQueue = team_app.state.queue
    async with logged_in_client(team_app) as client:
        agents = await make_agents(client, "Alice", "Bob", "Carol", "Dave")
        alice, bob, carol, dave = (agents[n] for n in ("Alice", "Bob", "Carol", "Dave"))
        assert alice["contacts"] == {"mode": "all", "agent_ids": []}
        # Bob talks to nobody; Alice may only talk to Dave.
        headers = await csrf_headers(client)
        r = await client.patch(
            f"/api/v1/agents/{bob['id']}", json={"contacts": {"mode": "none"}}, headers=headers
        )
        assert r.status_code == 200 and r.json()["contacts"]["mode"] == "none"
        r = await client.patch(
            f"/api/v1/agents/{alice['id']}",
            json={"contacts": {"mode": "list", "agent_ids": [dave["id"]]}},
            headers=headers,
        )
        assert r.json()["contacts"] == {"mode": "list", "agent_ids": [dave["id"]]}
        bad = await client.patch(
            f"/api/v1/agents/{alice['id']}",
            json={"contacts": {"mode": "list", "agent_ids": [str(uuid.uuid4())]}},
            headers=headers,
        )
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_contacts"

        task_id = (await run_agent(client, alice["id"], "Talk")).json()["task"]["id"]
        await drain(team_app, queue)

    rows = await calls(team_app, task_id)
    assert [(c.tool_name, c.status) for c in rows] == [
        ("agent_ask", "denied"),
        ("agent_tell", "denied"),
        ("agents_list", "succeeded"),
    ]
    assert "does not accept messages" not in (rows[0].result or "")  # Alice's own list first
    assert "not in your contacts" in (rows[0].result or "")
    assert "not in your contacts" in (rows[1].result or "")
    assert "Dave" in (rows[2].result or "") and "Bob" not in (rows[2].result or "")
    refused = [(m.error, m.status, m.content) for m in await messages(team_app)]
    assert refused == [
        ("not_in_contacts", "refused", {}),
        ("not_in_contacts", "refused", {}),
    ]
    assert len(await audit_actions(team_app, "agent.message_refused")) == 2
    assert not await consults(team_app)
    assert (await task_of(team_app, task_id)).status == "completed"
    _ = (bob, carol)


async def test_receiver_with_no_contacts_refuses(
    team_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        mock_provider,
        "_handlers",
        [per_agent({"Alice": [("agent_ask", {"agent": "bob", "request": "hi"}), "ok"]})],
    )
    async with logged_in_client(team_app) as client:
        agents = await make_agents(client, "Alice")
        await create_agent(client, name="Bob", contacts={"mode": "none"})
        task_id = (await run_agent(client, agents["Alice"]["id"], "Talk")).json()["task"]["id"]
        await drain(team_app, team_app.state.queue)
    [row] = await calls(team_app, task_id)
    assert row.status == "denied" and "does not accept messages from you" in (row.result or "")
    assert [m.error for m in await messages(team_app)] == ["receiver_refuses"]


async def test_a_cycle_is_refused(team_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mock_provider,
        "_handlers",
        [
            per_agent(
                {
                    "Alice": [
                        ("agent_ask", {"agent": "Bob", "request": "help"}),
                        lambda req: "Alice: " + last_tool_result(req),
                    ],
                    "Bob": [
                        ("agent_ask", {"agent": "Alice", "request": "and you?"}),
                        lambda req: "Bob: " + last_tool_result(req),
                    ],
                }
            )
        ],
    )
    async with logged_in_client(team_app) as client:
        agents = await make_agents(client, "Alice", "Bob")
        task_id = (await run_agent(client, agents["Alice"]["id"], "Go")).json()["task"]["id"]
        await drain(team_app, team_app.state.queue)
    [consult] = await consults(team_app)
    [bob_call] = await calls(team_app, consult.id)
    assert bob_call.status == "denied" and "chain of questions" in (bob_call.result or "")
    assert (await task_of(team_app, task_id)).status == "completed"
    assert "cycle" in [m.error for m in await messages(team_app)]


async def test_chain_depth_is_limited(
    app_factory: AppFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = await app_factory(workspace_root=str(tmp_path / "ws"), agent_ask_max_hops=1)
    async with app.state.db.sessionmaker() as db:
        await UserService(db).create_owner(OWNER_USERNAME, OWNER_PASSWORD, "Owner")
    app.state.queue = RecordingQueue()
    monkeypatch.setattr(
        mock_provider,
        "_handlers",
        [
            per_agent(
                {
                    "Alice": [("agent_ask", {"agent": "Bob", "request": "a"}), "done"],
                    "Bob": [("agent_ask", {"agent": "Carol", "request": "b"}), "bob done"],
                    "Carol": ["never asked"],
                }
            )
        ],
    )
    async with logged_in_client(app) as client:
        agents = await make_agents(client, "Alice", "Bob", "Carol")
        task_id = (await run_agent(client, agents["Alice"]["id"], "Go")).json()["task"]["id"]
        await drain(app, app.state.queue)
    [consult] = await consults(app)  # Carol was never asked
    [bob_call] = await calls(app, consult.id)
    assert bob_call.status == "denied" and "too long" in (bob_call.result or "")
    assert (await task_of(app, task_id)).status == "completed"


async def test_questions_per_task_are_limited(
    app_factory: AppFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = await app_factory(workspace_root=str(tmp_path / "ws"), agent_asks_per_task=1)
    async with app.state.db.sessionmaker() as db:
        await UserService(db).create_owner(OWNER_USERNAME, OWNER_PASSWORD, "Owner")
    app.state.queue = RecordingQueue()
    monkeypatch.setattr(
        mock_provider,
        "_handlers",
        [
            per_agent(
                {
                    "Alice": [
                        ("agent_ask", {"agent": "Bob", "request": "one"}),
                        ("agent_ask", {"agent": "Bob", "request": "two"}),
                        "done",
                    ],
                    "Bob": ["answer"],
                }
            )
        ],
    )
    async with logged_in_client(app) as client:
        agents = await make_agents(client, "Alice", "Bob")
        task_id = (await run_agent(client, agents["Alice"]["id"], "Go")).json()["task"]["id"]
        await drain(app, app.state.queue)
    rows = await calls(app, task_id)
    assert [c.status for c in rows] == ["succeeded", "denied"]
    assert "as many questions as allowed" in (rows[1].result or "")
    assert len(await consults(app)) == 1


async def test_a_deadlock_is_refused(team_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    """Alice waits for busy Carol; Carol's own task then asks Alice → would block both."""
    monkeypatch.setattr(
        mock_provider,
        "_handlers",
        [
            per_agent(
                {
                    "Alice": [("agent_ask", {"agent": "Carol", "request": "x"}), "alice done"],
                    "Carol": [
                        ("agent_ask", {"agent": "Alice", "request": "y"}),
                        lambda req: "carol: " + last_tool_result(req),
                    ],
                }
            )
        ],
    )
    queue: RecordingQueue = team_app.state.queue
    async with logged_in_client(team_app) as client:
        agents = await make_agents(client, "Alice", "Carol")
        carol_task = (await run_agent(client, agents["Carol"]["id"], "Own")).json()["task"]["id"]
        alice_task = (await run_agent(client, agents["Alice"]["id"], "Ask")).json()["task"]["id"]
        queue.enqueued.remove(uuid.UUID(carol_task))  # Carol is busy but not started yet
        await step(team_app)  # Alice asks Carol and waits (Carol is busy: question waits)
        [consult] = await consults(team_app)
        assert consult.status == "created"
        queue.enqueued.append(uuid.UUID(carol_task))
        await drain(team_app, queue)
    [carol_call] = await calls(team_app, carol_task)
    assert carol_call.status == "denied" and "block you both" in (carol_call.result or "")
    assert (await task_of(team_app, carol_task)).status == "completed"
    assert (await task_of(team_app, alice_task)).status == "completed"  # Carol answered later


async def test_supervised_agent_needs_approval_to_ask(
    team_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        mock_provider,
        "_handlers",
        [
            per_agent(
                {
                    "Alice": [
                        ("agent_ask", {"agent": "Bob", "request": "Review my plan"}),
                        lambda req: last_tool_result(req),
                    ],
                    "Bob": ["Looks good."],
                }
            )
        ],
    )
    queue: RecordingQueue = team_app.state.queue
    async with logged_in_client(team_app) as client:
        agents = await make_agents(client, "Alice", "Bob", autonomy="supervised")
        task_id = (await run_agent(client, agents["Alice"]["id"], "Plan")).json()["task"]["id"]
        await drain(team_app, queue)
        assert (await task_of(team_app, task_id)).status == "waiting_approval"
        assert not await consults(team_app)  # nothing was asked yet
        [approval] = await approvals(team_app, task_id)
        assert approval.tool_name == "agent_ask" and approval.category == "write"
        assert approval.summary.startswith("Ask agent Bob: Review my plan")
        assert "agent:Bob" in approval.resources
        assert "Bob gets a task" in approval.consequences
        assert (await decide(client, approval.id, "approve")).status_code == 200
        await drain(team_app, queue)
    assert (await task_of(team_app, task_id)).status == "completed"
    [consult] = await consults(team_app)
    assert consult.status == "completed"


async def test_no_answer_in_time(team_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mock_provider,
        "_handlers",
        [
            per_agent(
                {
                    "Alice": [
                        ("agent_ask", {"agent": "Bob", "request": "slow one"}),
                        lambda req: "Alice: " + last_tool_result(req),
                    ],
                    "Bob": ["too late"],
                }
            )
        ],
    )
    queue: RecordingQueue = team_app.state.queue
    async with logged_in_client(team_app) as client:
        agents = await make_agents(client, "Alice", "Bob")
        task_id = (await run_agent(client, agents["Alice"]["id"], "Ask")).json()["task"]["id"]
        await step(team_app)
        queue.enqueued.clear()  # Bob's job is "lost": the question sits queued
        async with team_app.state.db.sessionmaker() as db:
            found = await db.execute(select(Task).where(Task.task_type == "consult"))
            consult = found.scalar_one()
            past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
            consult.extra = {**consult.extra, "ask": {**consult.extra["ask"], "deadline": past}}
            await db.commit()
        assert await team.sweep(team_app.state.db.sessionmaker, queue) == 1
        await drain(team_app, queue)
        bob = (await client.get(f"/api/v1/agents/{agents['Bob']['id']}")).json()
    consult = (await consults(team_app))[0]
    assert (consult.status, consult.status_reason) == ("cancelled", "ask_timeout")
    asker = await task_of(team_app, task_id)
    assert asker.status == "completed" and "No answer in time" in (asker.result or "")
    assert bob["status"] == "idle" and bob["current_task_id"] is None
    assert [m.message_type for m in await messages(team_app)] == ["request", "error"]


async def test_cancelling_the_asker_cancels_its_question(
    team_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        mock_provider,
        "_handlers",
        [per_agent({"Alice": [("agent_ask", {"agent": "Bob", "request": "q"}), "x"]})],
    )
    queue: RecordingQueue = team_app.state.queue
    async with logged_in_client(team_app) as client:
        agents = await make_agents(client, "Alice", "Bob")
        task_id = (await run_agent(client, agents["Alice"]["id"], "Ask")).json()["task"]["id"]
        await step(team_app)  # Alice waits; Bob's consult is queued (Bob reserved)
        r = await client.post(f"/api/v1/tasks/{task_id}/cancel", headers=await csrf_headers(client))
        assert r.status_code == 200
        await drain(team_app, queue)
        bob = (await client.get(f"/api/v1/agents/{agents['Bob']['id']}")).json()
    [consult] = await consults(team_app)
    assert (consult.status, consult.status_reason) == ("cancelled", "parent_cancelled")
    assert bob["status"] == "idle" and bob["current_task_id"] is None
    assert [m.message_type for m in await messages(team_app)] == ["request"]  # nobody to answer


async def test_cancelling_the_question_answers_the_asker_with_an_error(
    team_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        mock_provider,
        "_handlers",
        [
            per_agent(
                {
                    "Alice": [
                        ("agent_ask", {"agent": "Bob", "request": "q"}),
                        lambda req: "Alice: " + last_tool_result(req),
                    ]
                }
            )
        ],
    )
    queue: RecordingQueue = team_app.state.queue
    async with logged_in_client(team_app) as client:
        agents = await make_agents(client, "Alice", "Bob")
        task_id = (await run_agent(client, agents["Alice"]["id"], "Ask")).json()["task"]["id"]
        await step(team_app)
        [consult] = await consults(team_app)
        r = await client.post(
            f"/api/v1/tasks/{consult.id}/cancel", headers=await csrf_headers(client)
        )
        assert r.status_code == 200
        assert uuid.UUID(task_id) in queue.enqueued  # answered right away, not at the sweep
        await drain(team_app, queue)
    asker = await task_of(team_app, task_id)
    assert asker.status == "completed"
    assert "Bob did not answer: the question was cancelled" in (asker.result or "")
    [row] = await calls(team_app, task_id)
    assert row.status == "failed" and row.is_error


async def test_resume_and_restart_never_ask_twice(
    team_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        mock_provider,
        "_handlers",
        [
            per_agent(
                {
                    "Alice": [
                        ("agent_ask", {"agent": "Bob", "request": "q"}),
                        lambda req: "Alice: " + last_tool_result(req),
                    ],
                    "Bob": ["the answer"],
                }
            )
        ],
    )
    queue: RecordingQueue = team_app.state.queue
    async with logged_in_client(team_app) as client:
        agents = await make_agents(client, "Alice", "Bob")
        alice = agents["Alice"]
        task_id = (await run_agent(client, alice["id"], "Ask")).json()["task"]["id"]
        await step(team_app)
        queue.enqueued.clear()  # keep Bob's question waiting
        # A restart leaves the waiting task alone.
        await recover(team_app.state.db.sessionmaker, None)
        assert (await task_of(team_app, task_id)).status == "waiting"
        # The owner presses "resume" while the question is open: Alice just waits again.
        r = await client.post(
            f"/api/v1/agents/{alice['id']}/resume", headers=await csrf_headers(client)
        )
        assert r.status_code == 200
        await step(team_app)
        asker = await task_of(team_app, task_id)
        assert (asker.status, asker.status_reason) == ("waiting", "waiting_for_agent")
        assert len(await consults(team_app)) == 1
        # Bob answers; Alice continues with exactly that one answer.
        consult = (await consults(team_app))[0]
        queue.enqueued.append(consult.id)
        await drain(team_app, queue)
    assert (await task_of(team_app, task_id)).status == "completed"
    rows = await calls(team_app, task_id)
    assert [(c.tool_name, c.status) for c in rows] == [("agent_ask", "succeeded")]
    assert len(await consults(team_app)) == 1
    assert len(await audit_actions(team_app, "agent.asked")) == 1


async def test_kill_switch_stops_questions(
    team_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        mock_provider,
        "_handlers",
        [per_agent({"Alice": [("agent_ask", {"agent": "Bob", "request": "q"}), "x"]})],
    )
    queue: RecordingQueue = team_app.state.queue
    async with logged_in_client(team_app) as client:
        agents = await make_agents(client, "Alice", "Bob")
        task_id = (await run_agent(client, agents["Alice"]["id"], "Ask")).json()["task"]["id"]
        await step(team_app)
        r = await client.post("/api/v1/system/stop-all", headers=await csrf_headers(client))
        assert r.status_code == 200
        await drain(team_app, queue)
    assert (await task_of(team_app, task_id)).status == "cancelled"
    assert [c.status for c in await consults(team_app)] == ["cancelled"]


OWNER = uuid.uuid4()


def _agent(kind: str, *, run: uuid.UUID | None = None, status: str = "idle", **kw: Any) -> Any:
    from app.models import Agent

    return Agent(
        id=uuid.uuid4(),
        user_id=kw.pop("user", OWNER),
        name=kind,
        agent_type=kind,
        run_id=run,
        status=status,
        contacts=kw.pop("contacts", {}),
        archived_at=kw.pop("archived_at", None),
    )


def test_who_may_talk_to_whom() -> None:
    run, other_run = uuid.uuid4(), uuid.uuid4()
    sub, sibling = _agent("subagent", run=run), _agent("subagent", run=run)
    assert team.contact_problem(sub, sibling) is None  # siblings of one run
    assert team.contact_problem(sub, _agent("subagent", run=other_run)) == "different_run"
    assert team.contact_problem(sub, _agent("autonomous")) == "different_run"
    finished = _agent("subagent", run=run, status="completed")
    assert team.contact_problem(sub, finished) == "agent_unavailable"
    me, colleague = _agent("autonomous"), _agent("autonomous")
    assert team.contact_problem(me, colleague) is None
    assert team.contact_problem(me, me) == "self"
    assert team.contact_problem(me, _agent("orchestrator")) == "orchestrator"
    assert team.contact_problem(me, sub) == "not_a_colleague"
    assert team.contact_problem(me, _agent("autonomous", user=uuid.uuid4())) == "different_owner"
    gone = _agent("autonomous", archived_at=datetime.now(UTC))
    assert team.contact_problem(me, gone) == "agent_unavailable"
    picky = _agent("autonomous", contacts={"mode": "list", "agent_ids": [str(colleague.id)]})
    assert team.contact_problem(picky, colleague) is None
    assert team.contact_problem(picky, me) == "not_in_contacts"
    assert team.contact_problem(me, picky) == "receiver_refuses"
    # A value we do not understand never widens access.
    odd = _agent("autonomous", contacts={"mode": "everyone"})
    assert team.contact_problem(odd, me) == "not_in_contacts"
