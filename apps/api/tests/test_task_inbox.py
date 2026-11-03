"""The owner writes to a task at any time before it ends and sends it files: a task still
waiting in line reads the notes first thing; the Orchestrator passes them to the parts at
work and reads them when it plans and merges; files land in the task's workspace."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.models.agent import AgentRun
from app.models.task import Task
from app.providers import mock_provider
from app.providers.base import ChatRequest, ChatResult
from tests.conftest import csrf_headers, drain, executor_for, logged_in_client, run_agent
from tests.test_tools_engine import task_of, tool_app, ws_file  # noqa: F401 — fixture
from tests.tools_helpers import tool_agent


def texts(req: ChatRequest) -> str:
    return "\n".join(m.content for m in req.messages)


async def test_a_note_to_a_task_in_line_is_read_before_its_first_step(
    tool_app: FastAPI,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[ChatRequest] = []

    def model(req: ChatRequest) -> ChatResult:
        seen.append(req)
        return ChatResult(text="Done.")

    monkeypatch.setattr(mock_provider, "_handlers", [model])
    async with logged_in_client(tool_app) as client:
        headers = await csrf_headers(client)
        agent = await tool_agent(client, tools=["fs_write"])
        await run_agent(client, agent["id"], "One")
        second = (await run_agent(client, agent["id"], "Two")).json()["task"]["id"]
        waiting = await task_of(tool_app, second)
        assert (waiting.status, waiting.run_id) == ("created", None)

        for text in ("Use short words", "And add a title"):
            resp = await client.post(
                f"/api/v1/tasks/{second}/message", json={"text": text}, headers=headers
            )
            assert resp.status_code == 200, resp.text
        notes = (await task_of(tool_app, second)).extra["pending_inbox"]
        assert [n["text"] for n in notes] == ["Use short words", "And add a title"]
        await drain(tool_app, tool_app.state.queue)

    done = await task_of(tool_app, second)
    assert done.status == "completed" and "pending_inbox" not in done.extra
    [first_step] = [r for r in seen if r.messages[0].content.startswith("# Task: Two")]
    assert "Message from the owner" in texts(first_step)
    assert "Use short words" in texts(first_step) and "And add a title" in texts(first_step)


async def test_a_note_to_the_orchestrator_reaches_its_plan_its_parts_and_its_merge(
    tool_app: FastAPI,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.orchestrator.mock_script import scripted
    from app.orchestrator.prompts import PROTOCOL_PLAN

    seen: list[ChatRequest] = []

    def capture(req: ChatRequest) -> ChatResult | None:
        seen.append(req)
        return None

    monkeypatch.setattr(mock_provider, "_handlers", [capture, scripted])
    async with logged_in_client(tool_app) as client:
        headers = await csrf_headers(client)
        await tool_agent(client, tools=["fs_write"])  # a model for the Orchestrator
        started = await client.post(
            "/api/v1/runs", json={"title": "Improve the site [[mock:plan:2]]"}, headers=headers
        )
        assert started.status_code == 200, started.text
        task_id = started.json()["task"]["id"]

        async def say(text: str) -> None:
            resp = await client.post(
                f"/api/v1/tasks/{task_id}/message", json={"text": text}, headers=headers
            )
            assert resp.status_code == 200, resp.text

        await say("Keep it in Russian")  # before it plans
        queue = tool_app.state.queue
        queue.enqueued.remove(uuid.UUID(task_id))
        await executor_for(tool_app).execute(uuid.UUID(task_id))  # plans, starts the parts
        async with tool_app.state.db.sessionmaker() as db:
            parts = list(
                (
                    await db.execute(select(Task).where(Task.parent_task_id == uuid.UUID(task_id)))
                ).scalars()
            )
        assert len(parts) == 2
        await say("Mention the price")  # while the parts work
        for part in parts:
            fresh = await task_of(tool_app, str(part.id))
            if fresh.run_id is None:
                assert fresh.extra["pending_inbox"][0]["text"] == "Mention the price"
            else:
                async with tool_app.state.db.sessionmaker() as db:
                    run = await db.get(AgentRun, fresh.run_id)
                    assert run is not None
                    assert run.state["owner_inbox"][0]["text"] == "Mention the price"
        await drain(tool_app, queue)

    assert (await task_of(tool_app, task_id)).status == "completed"
    [plan] = [r for r in seen if PROTOCOL_PLAN in (r.system or "")]
    assert "Keep it in Russian" in texts(plan) and "Mention the price" not in texts(plan)
    part_steps = [r for r in seen if r.messages[0].content.startswith("# Task: Part")]
    assert part_steps and all("Mention the price" in texts(r) for r in part_steps)
    merge = seen[-1]
    assert "Mention the price" in texts(merge) and "Keep it in Russian" not in texts(merge)


async def test_files_sent_to_a_task_land_in_its_workspace_inbox(
    tool_app: FastAPI,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mock_provider, "_handlers", [lambda req: ChatResult(text="Done.")])
    async with logged_in_client(tool_app) as client:
        headers = await csrf_headers(client)
        agent = await tool_agent(client, tools=["fs_read"])
        task_id = (await run_agent(client, agent["id"], "Look at my photo")).json()["task"]["id"]

        async def send(name: str, data: bytes) -> dict[str, object]:
            resp = await client.post(
                f"/api/v1/tasks/{task_id}/files",
                files={"file": (name, data, "image/png")},
                headers=headers,
            )
            assert resp.status_code == 201, resp.text
            return dict(resp.json())

        first = await send("../../photo.png", b"one")
        again = await send("photo.png", b"two")
        assert first["path"] == "inbox/photo.png" and again["path"] == "inbox/photo-2.png"
        assert first["size"] == 3 and first["filename"] == "photo.png"
        [one] = ws_file(tool_app, "inbox/photo.png")
        [two] = ws_file(tool_app, "inbox/photo-2.png")
        assert one.read_bytes() == b"one" and two.read_bytes() == b"two"
        assert not [p for p in one.parent.iterdir() if p.name.startswith(".upload-")]

        await drain(tool_app, tool_app.state.queue)
        late = await client.post(
            f"/api/v1/tasks/{task_id}/files",
            files={"file": ("late.txt", b"x", "text/plain")},
            headers=headers,
        )
        assert late.status_code == 409
        other = await client.post(
            f"/api/v1/tasks/{uuid.uuid4()}/files",
            files={"file": ("x.txt", b"x", "text/plain")},
            headers=headers,
        )
        assert other.status_code == 404
    assert not ws_file(tool_app, "inbox/late.txt")


def test_a_git_workspace_keeps_the_inbox_out_of_commits(tmp_path: Path) -> None:
    from app.services.task_files import _place

    (tmp_path / ".git" / "info").mkdir(parents=True)
    (tmp_path / ".git" / "info" / "exclude").write_text("# git ls-files --others\n")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for _ in range(2):
        temp = inbox / ".upload-x"
        temp.write_bytes(b"x")
        _place(temp, inbox, "a.txt", tmp_path)
    lines = (tmp_path / ".git" / "info" / "exclude").read_text().splitlines()
    assert lines == ["# git ls-files --others", "/inbox/"]
    assert sorted(p.name for p in inbox.iterdir()) == ["a-2.txt", "a.txt"]
