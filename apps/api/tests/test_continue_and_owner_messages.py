"""Full control over a working agent: a stopped task continues from where it stopped (its
saved conversation, not from scratch), and the owner can write to an agent mid-task — the
message is read once, before the agent's next step, also after an approval wait."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.models.agent import AgentRun
from app.models.event import AgentEvent
from app.providers import mock_provider
from app.providers.base import ChatRequest, ChatResult
from app.providers.base import ToolCall as ModelToolCall
from tests.conftest import csrf_headers, drain, logged_in_client, run_agent
from tests.test_tools_engine import task_of, tool_app, ws_file  # noqa: F401 — fixture
from tests.tools_helpers import decide, tool_agent, tool_calls


def write_call(path: str) -> ChatResult:
    return ChatResult(
        text="",
        tool_calls=(ModelToolCall(f"call_{path}", "fs_write", {"path": path, "content": "x"}),),
    )


async def run_state(app: FastAPI, task_id: str) -> dict[str, Any]:
    task = await task_of(app, task_id)
    async with app.state.db.sessionmaker() as db:
        run = await db.get(AgentRun, task.run_id)
        assert run is not None
        return dict(run.state)


async def test_a_failed_task_continues_from_where_it_stopped(
    tool_app: FastAPI,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[ChatRequest] = []

    def model(req: ChatRequest) -> ChatResult:
        seen.append(req)
        if len(seen) == 1:
            return write_call("part1.txt")
        if len(seen) == 2:  # the first attempt ends with nothing — "empty_result"
            return ChatResult(text="", stop_reason="end_turn")
        return ChatResult(text="Both parts done.", stop_reason="end_turn")

    monkeypatch.setattr(mock_provider, "_handlers", [model])
    async with logged_in_client(tool_app) as client:
        agent = await tool_agent(client, tools=["fs_write"])
        old_id = (await run_agent(client, agent["id"], "Write two parts")).json()["task"]["id"]
        await drain(tool_app, tool_app.state.queue)
        assert (await task_of(tool_app, old_id)).error_code == "empty_result"

        resp = await client.post(
            f"/api/v1/tasks/{old_id}/continue",
            json={"instruction": "Write the second part now"},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 200, resp.text
        new = resp.json()
        assert new["attempt"] == 2 and new["retry_of_id"] == old_id
        await drain(tool_app, tool_app.state.queue)

        # The same folder: the continued attempt sees the first one's files ("start over"
        # gets a fresh one).
        def ws_of(task_id: str) -> Any:
            return client.get(f"/api/v1/tasks/{task_id}/workspace")

        assert (await ws_of(old_id)).json()["id"] == (await ws_of(new["id"])).json()["id"]

    task = await task_of(tool_app, new["id"])
    assert task.status == "completed" and task.result == "Both parts done."
    assert task.extra["continued_from"] == old_id
    # Nothing was redone: the first part was written once, by the first attempt.
    assert [c.tool_name for c in await tool_calls(tool_app, old_id)] == ["fs_write"]
    assert await tool_calls(tool_app, new["id"]) == []
    assert ws_file(tool_app, "part1.txt")
    # The continued attempt saw the earlier work, without the empty reply, plus the note.
    history = seen[2].messages
    assert any(m.tool_calls and m.tool_calls[0].name == "fs_write" for m in history)
    assert not any(m.role == "assistant" and not m.content and not m.tool_calls for m in history)
    note = history[-1]
    assert note.role == "user" and "continue from where you stopped" in note.content
    assert "empty_result" in note.content and "Write the second part now" in note.content
    assert len(seen) == 3  # the continuation did not start over from the first step


async def test_a_task_that_never_ran_is_continued_as_a_plain_retry(
    tool_app: FastAPI,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[ChatRequest] = []

    def model(req: ChatRequest) -> ChatResult:
        seen.append(req)
        return ChatResult(text="Done.")

    monkeypatch.setattr(mock_provider, "_handlers", [model])
    async with logged_in_client(tool_app) as client:
        agent = await tool_agent(client, tools=["fs_write"])
        old_id = (await run_agent(client, agent["id"], "Quick one")).json()["task"]["id"]
        headers = await csrf_headers(client)
        assert (await client.post(f"/api/v1/tasks/{old_id}/cancel", headers=headers)).is_success
        tool_app.state.queue.enqueued.clear()
        resp = await client.post(f"/api/v1/tasks/{old_id}/continue", json={}, headers=headers)
        assert resp.status_code == 200, resp.text
        await drain(tool_app, tool_app.state.queue)
        # Only failed or cancelled tasks can be continued.
        again = await client.post(
            f"/api/v1/tasks/{resp.json()['id']}/continue", json={}, headers=headers
        )
        assert again.status_code == 409
    assert (await task_of(tool_app, resp.json()["id"])).status == "completed"
    assert seen[0].messages[0].content.startswith("# Task: Quick one")


async def test_the_owner_writes_to_a_working_agent(
    tool_app: FastAPI,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[ChatRequest] = []

    def model(req: ChatRequest) -> ChatResult:
        seen.append(req)
        return write_call("a.txt") if len(seen) == 1 else ChatResult(text="Done, in English.")

    monkeypatch.setattr(mock_provider, "_handlers", [model])
    async with logged_in_client(tool_app) as client:
        headers = await csrf_headers(client)
        agent = await tool_agent(client, autonomy="supervised", tools=["fs_write"])
        task_id = (await run_agent(client, agent["id"], "Write a file")).json()["task"]["id"]
        await drain(tool_app, tool_app.state.queue)
        assert (await task_of(tool_app, task_id)).status == "waiting_approval"

        # Written while the agent waits for an approval: read before its next step.
        resp = await client.post(
            f"/api/v1/tasks/{task_id}/message", json={"text": "Answer in English"}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        assert (await run_state(tool_app, task_id))["owner_inbox"][0]["text"] == "Answer in English"
        pending = (await client.get("/api/v1/approvals?status=pending")).json()
        assert (await decide(client, pending[0]["id"], "approve")).status_code == 200
        await drain(tool_app, tool_app.state.queue)

        # A finished task takes no more messages (continue it instead).
        late = await client.post(
            f"/api/v1/tasks/{task_id}/message", json={"text": "one more"}, headers=headers
        )
        assert late.status_code == 409
        empty = await client.post(
            f"/api/v1/tasks/{task_id}/message", json={"text": ""}, headers=headers
        )
        assert empty.status_code == 422

    assert (await task_of(tool_app, task_id)).status == "completed"
    last = seen[1].messages
    assert last[-1].role == "user" and "Message from the owner" in last[-1].content
    assert "Answer in English" in last[-1].content
    assert last[-2].tool_call_id is not None  # after the tool's result
    # read exactly once, and the inbox is empty again
    assert sum("Answer in English" in m.content for m in last) == 1
    assert (await run_state(tool_app, task_id))["owner_inbox"] == []
    async with tool_app.state.db.sessionmaker() as db:
        types = (
            await db.execute(
                select(AgentEvent.type).where(AgentEvent.task_id == uuid.UUID(task_id))
            )
        ).scalars()
        assert {"task.owner_message", "task.owner_message_read"} <= set(types)


async def test_messages_the_agent_never_read_carry_over_to_the_continued_attempt(
    tool_app: FastAPI,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[ChatRequest] = []

    def model(req: ChatRequest) -> ChatResult:
        seen.append(req)
        return write_call("a.txt") if len(seen) == 1 else ChatResult(text="Done.")

    monkeypatch.setattr(mock_provider, "_handlers", [model])
    async with logged_in_client(tool_app) as client:
        headers = await csrf_headers(client)
        agent = await tool_agent(client, autonomy="supervised", tools=["fs_write"])
        old_id = (await run_agent(client, agent["id"], "Write a file")).json()["task"]["id"]
        await drain(tool_app, tool_app.state.queue)
        await client.post(
            f"/api/v1/tasks/{old_id}/message", json={"text": "Name it b.txt"}, headers=headers
        )
        assert (await client.post(f"/api/v1/tasks/{old_id}/cancel", headers=headers)).is_success
        resp = await client.post(f"/api/v1/tasks/{old_id}/continue", json={}, headers=headers)
        assert resp.status_code == 200, resp.text
        await drain(tool_app, tool_app.state.queue)

    # the unanswered tool request was dropped: the agent decides again, with the message
    note = seen[1].messages[-1]
    assert note.role == "user" and "it was cancelled" in note.content
    assert "Message from the owner" in note.content and "Name it b.txt" in note.content
    assert not any(m.tool_calls for m in seen[1].messages)
    assert (await task_of(tool_app, resp.json()["id"])).status == "completed"
    # nothing ran without the approval
    assert all(c.status != "succeeded" for c in await tool_calls(tool_app, old_id))
    assert not ws_file(tool_app, "a.txt")


async def test_start_over_gets_a_fresh_folder_and_cleanup_spares_a_continued_one(
    tool_app: FastAPI,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime, timedelta

    from app.models.task import Task
    from app.services.workspaces import clean_task_workspaces, workspace_for_task

    def model(req: ChatRequest) -> ChatResult:
        return ChatResult(text="", stop_reason="end_turn")  # always "empty_result"

    monkeypatch.setattr(mock_provider, "_handlers", [model])
    settings = tool_app.state.settings.model_copy(update={"workspace_task_ttl_days": 1})
    async with logged_in_client(tool_app) as client:
        headers = await csrf_headers(client)
        agent = await tool_agent(client, tools=["fs_write"])
        first = (await run_agent(client, agent["id"], "Try")).json()["task"]["id"]
        await drain(tool_app, tool_app.state.queue)
        over = await client.post(f"/api/v1/tasks/{first}/retry", headers=headers)
        await drain(tool_app, tool_app.state.queue)
        continued = await client.post(f"/api/v1/tasks/{first}/continue", json={}, headers=headers)
        # (not drained: the continued attempt is still queued)

    async with tool_app.state.db.sessionmaker() as db:
        ids = [first, over.json()["id"], continued.json()["id"]]
        ws = [await workspace_for_task(db, settings, uuid.UUID(i)) for i in ids]
        assert ws[0].id == ws[2].id != ws[1].id
        long_ago = datetime.now(UTC) - timedelta(days=5)
        for i in ids[:2]:
            (await db.get(Task, uuid.UUID(i))).updated_at = long_ago
        await db.commit()
        assert await clean_task_workspaces(db, settings) == 1  # only "start over"'s folder
        await db.commit()
        await db.refresh(ws[0])
        await db.refresh(ws[1])
        assert ws[0].cleaned_at is None and ws[1].cleaned_at is not None
