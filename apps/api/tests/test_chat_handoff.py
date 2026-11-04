"""The chat hands work to the agents by itself; questions it answers itself."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.models import Task, User
from app.providers import mock_provider
from app.providers.base import ChatRequest, ChatResult
from app.services.chat_handoff import HANDOFF_INSTRUCTION, HANDOFF_MARKER
from tests.conftest import AppFactory, RecordingQueue, add_mock_model, drain, logged_in_client
from tests.test_chat_api import new_chat, send


async def test_work_goes_to_the_agents_and_the_answer_comes_back_into_the_chat(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        chat = await new_chat(client)
        events = await send(client, chat["id"], "Почини форму входа [[mock:work]]")
        names = [name for name, _ in events]
        assert names[0] == "message.created" and names[-1] == "message.handed_off"
        assert "message.completed" not in names
        handed = events[-1][1]
        page = (await client.get(f"/api/v1/chats/{chat['id']}/messages")).json()
        # The marker answer is gone; the owner's message links to the agents' run.
        assert [(m["role"], m["agent_run_id"]) for m in page["items"]] == [
            ("user", handed["run_id"])
        ]
        task = (await client.get(f"/api/v1/tasks/{handed['task_id']}")).json()["task"]
        assert task["extra"]["conversation_id"] == chat["id"]
        assert task["description"] == "Почини форму входа [[mock:work]]"
        await drain(app, queue)
        page = (await client.get(f"/api/v1/chats/{chat['id']}/messages")).json()
    assert [m["role"] for m in page["items"]] == ["user", "assistant"]
    answer = page["items"][1]
    assert answer["agent_run_id"] == handed["run_id"] and answer["status"] == "completed"
    assert HANDOFF_MARKER not in answer["content"]


async def test_questions_are_answered_in_the_chat(
    app: FastAPI, owner: User, queue: RecordingQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[ChatRequest] = []

    def capture(req: ChatRequest) -> ChatResult | None:
        seen.append(req)
        return None

    monkeypatch.setattr(mock_provider, "_handlers", [*mock_provider._handlers, capture])
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        chat = await new_chat(client)
        events = await send(client, chat["id"], "Сколько часовых поясов в Казахстане?")
    assert events[-1][0] == "message.completed"
    assert events[-1][1]["message"]["content"].startswith("Echo:")
    assert seen and HANDOFF_INSTRUCTION in (seen[-1].system or "")
    async with app.state.db.sessionmaker() as db:
        assert (await db.execute(select(Task))).scalars().all() == []


async def test_when_the_agents_cannot_take_it_the_answer_says_so(
    app: FastAPI, owner: User, queue: RecordingQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import chat_stream
    from app.services.tasks import AgentBusy

    async def busy(*args: Any, **kwargs: Any) -> Any:
        raise AgentBusy()

    monkeypatch.setattr(chat_stream, "hand_to_agents", busy)
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        chat = await new_chat(client)
        events = await send(client, chat["id"], "Сделай отчёт [[mock:work]]")
    name, data = events[-1]
    assert name == "message.failed"
    assert data["message"]["error_code"] == "handoff_failed" and data["message"]["content"] == ""


async def test_switched_off_the_chat_never_hands_off(
    app_factory: AppFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.users import UserService
    from tests.conftest import OWNER_PASSWORD, OWNER_USERNAME

    app = await app_factory(chat_auto_handoff=False)
    app.state.queue = RecordingQueue()
    async with app.state.db.sessionmaker() as db:
        await UserService(db).create_owner(OWNER_USERNAME, OWNER_PASSWORD, "Owner")
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        chat = await new_chat(client)
        events = await send(client, chat["id"], "Почини форму [[mock:work]]")
    assert events[-1][0] == "message.completed"
    assert events[-1][1]["message"]["content"].startswith("Echo:")
