from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.models import AuditLog, Conversation, Message, User
from app.providers import mock_provider
from app.providers.base import ChatRequest, ChatResult
from app.services.chat import ChatService
from app.services.chat_stream import StreamState
from tests.conftest import AppFactory, add_mock_model, csrf_headers, logged_in_client


async def read_sse(resp: httpx.Response) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    name: str | None = None
    data: list[str] = []
    async for line in resp.aiter_lines():
        if line.startswith(":"):
            continue
        if line.startswith("event: "):
            name = line[len("event: ") :]
        elif line.startswith("data: "):
            data.append(line[len("data: ") :])
        elif line == "" and name is not None:
            events.append((name, json.loads("\n".join(data))))
            name, data = None, []
    return events


async def new_chat(client: httpx.AsyncClient, **body: Any) -> dict[str, Any]:
    resp = await client.post("/api/v1/chats", json=body, headers=await csrf_headers(client))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def send(
    client: httpx.AsyncClient, chat_id: str, content: str
) -> list[tuple[str, dict[str, Any]]]:
    async with client.stream(
        "POST",
        f"/api/v1/chats/{chat_id}/messages",
        json={"content": content},
        headers=await csrf_headers(client),
    ) as resp:
        assert resp.status_code == 200, await resp.aread()
        assert resp.headers["content-type"].startswith("text/event-stream")
        return await read_sse(resp)


async def start_in_background(app: FastAPI, user: User, chat_id: str, content: str) -> StreamState:
    """Start a generation like the endpoint does, but without anyone listening."""
    async with app.state.db.sessionmaker() as db:
        _, _, state = await ChatService(db, app.state.settings, app.state.gateway).send(
            user.id, uuid.UUID(chat_id), content, None, app.state.chat_streams
        )
    return state


async def message_row(app: FastAPI, message_id: uuid.UUID | str) -> Message:
    async with app.state.db.sessionmaker() as db:
        row = await db.get(Message, uuid.UUID(str(message_id)))
    assert row is not None
    return row


async def test_send_streams_tokens_and_persists(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        chat = await new_chat(client)
        assert chat["title"] == "New chat"

        events = await send(client, chat["id"], "hello there")
        names = [n for n, _ in events]
        assert names[0] == "message.created"
        assert names[-1] == "message.completed"
        assert "message.delta" in names
        streamed = "".join(d["text"] for n, d in events if n == "message.delta")
        final = events[-1][1]["message"]
        assert streamed == final["content"] == "Echo: hello there"
        assert final["status"] == "completed"
        assert final["output_tokens"] == 3

        page = (await client.get(f"/api/v1/chats/{chat['id']}/messages")).json()
        assert [(m["role"], m["status"]) for m in page["items"]] == [
            ("user", "completed"),
            ("assistant", "completed"),
        ]
        chat_after = (await client.get(f"/api/v1/chats/{chat['id']}")).json()
        assert chat_after["title"] == "hello there"


async def test_history_is_sent_as_context(
    app: FastAPI, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[ChatRequest] = []

    def capture(req: ChatRequest) -> ChatResult | None:
        seen.append(req)
        return None

    monkeypatch.setattr(mock_provider, "_handlers", [capture])
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        chat = await new_chat(client)
        await send(client, chat["id"], "first")
        await send(client, chat["id"], "second")
    assert [(m.role, m.content) for m in seen[-1].messages] == [
        ("user", "first"),
        ("assistant", "Echo: first"),
        ("user", "second"),
    ]


async def test_provider_error_is_saved_as_failed_not_completed(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        chat = await new_chat(client)
        events = await send(client, chat["id"], "[[mock:error:rate_limited]]")
    name, data = events[-1]
    assert name == "message.failed"
    message = data["message"]
    assert message["status"] == "failed"
    assert message["error_code"] == "provider_rate_limited"
    assert "rate-limiting" in message["error_message"]
    assert message["error_id"]
    assert (await message_row(app, message["id"])).status == "failed"


async def test_auth_error_message_points_to_settings(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        chat = await new_chat(client)
        events = await send(client, chat["id"], "[[mock:error:auth_failed]]")
    assert events[-1][1]["message"]["error_code"] == "provider_auth_failed"


async def test_cancel_keeps_partial_answer(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        chat = await new_chat(client)
        state = await start_in_background(
            app, owner, chat["id"], "[[mock:slow]] one two three four five six"
        )
        await asyncio.sleep(0.6)
        resp = await client.post(
            f"/api/v1/chats/{chat['id']}/messages/{state.message_id}/cancel",
            headers=await csrf_headers(client),
        )
        assert resp.json() == {"cancelled": True}
    row = await message_row(app, state.message_id)
    assert row.status == "cancelled"
    assert row.content and len(row.content) < len("Echo: one two three four five six")


async def test_one_answer_at_a_time_per_chat(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        chat = await new_chat(client)
        state = await start_in_background(app, owner, chat["id"], "[[mock:slow]] a b c d e f")
        resp = await client.post(
            f"/api/v1/chats/{chat['id']}/messages",
            json={"content": "again"},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "generation_in_progress"
        await app.state.chat_streams.cancel(state.message_id, owner.id)


async def test_answer_completes_without_any_listener(app: FastAPI, owner: User) -> None:
    """Closing the browser must not lose the answer."""
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        chat = await new_chat(client)
    state = await start_in_background(app, owner, chat["id"], "nobody is watching")
    assert state.task is not None
    await state.task
    row = await message_row(app, state.message_id)
    assert (row.status, row.content) == ("completed", "Echo: nobody is watching")


async def test_reattach_to_running_and_finished_answers(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        chat = await new_chat(client)
        state = await start_in_background(app, owner, chat["id"], "[[mock:slow]] x y z")
        await asyncio.sleep(0.3)
        url = f"/api/v1/chats/{chat['id']}/messages/{state.message_id}/stream"
        async with client.stream("GET", url) as resp:
            events = await read_sse(resp)
        assert events[0][0] == "message.snapshot"
        snapshot = events[0][1]["text"]
        deltas = "".join(d["text"] for n, d in events if n == "message.delta")
        assert snapshot + deltas == "Echo: x y z"
        assert events[-1][0] == "message.completed"

        # After it finished, attaching returns the saved result immediately.
        async with client.stream("GET", url) as resp:
            events = await read_sse(resp)
        assert [n for n, _ in events] == ["message.completed"]


async def test_no_model_configured_is_a_clear_error(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        chat = await new_chat(client)
        resp = await client.post(
            f"/api/v1/chats/{chat['id']}/messages",
            json={"content": "hi"},
            headers=await csrf_headers(client),
        )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "no_model_configured"


async def test_disabled_model_is_rejected(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        model = await add_mock_model(client)
        chat = await new_chat(client, model_config_id=model["id"])
        await client.patch(
            f"/api/v1/models/{model['id']}",
            json={"enabled": False},
            headers=await csrf_headers(client),
        )
        resp = await client.post(
            f"/api/v1/chats/{chat['id']}/messages",
            json={"content": "hi"},
            headers=await csrf_headers(client),
        )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "model_unavailable"


async def test_cost_is_estimated_when_prices_are_set(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        model = await add_mock_model(client)
        await client.patch(
            f"/api/v1/models/{model['id']}",
            json={"input_price_per_mtok": "1000000", "output_price_per_mtok": "1000000"},
            headers=await csrf_headers(client),
        )
        chat = await new_chat(client)
        events = await send(client, chat["id"], "price me")
    message = events[-1][1]["message"]
    # 2 input words + 3 output words at $1/token
    assert float(message["cost_usd"]) == pytest.approx(5.0)


async def test_messages_and_chats_paginate(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        chat = await new_chat(client)
        for i in range(3):
            await send(client, chat["id"], f"m{i}")
        page1 = (await client.get(f"/api/v1/chats/{chat['id']}/messages?limit=4")).json()
        assert [m["content"] for m in page1["items"]] == ["m1", "Echo: m1", "m2", "Echo: m2"]
        page2 = (
            await client.get(
                f"/api/v1/chats/{chat['id']}/messages?limit=4&cursor={page1['next_cursor']}"
            )
        ).json()
        assert [m["content"] for m in page2["items"]] == ["m0", "Echo: m0"]
        assert page2["next_cursor"] is None

        for _ in range(2):
            await new_chat(client)
        chats = (await client.get("/api/v1/chats?limit=2")).json()
        assert len(chats["items"]) == 2 and chats["next_cursor"]
        rest = (await client.get(f"/api/v1/chats?limit=2&cursor={chats['next_cursor']}")).json()
        assert len(rest["items"]) == 1
        bad = await client.get("/api/v1/chats?cursor=garbage")
        assert bad.status_code == 422


async def test_delete_chat_removes_messages_and_is_audited(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        chat = await new_chat(client)
        await send(client, chat["id"], "bye")
        resp = await client.delete(
            f"/api/v1/chats/{chat['id']}", headers=await csrf_headers(client)
        )
        assert resp.status_code == 204
        assert (await client.get(f"/api/v1/chats/{chat['id']}")).status_code == 404
    async with app.state.db.sessionmaker() as db:
        assert (await db.execute(select(Message))).first() is None
        actions = [a.action for a in (await db.execute(select(AuditLog))).scalars()]
    assert "conversation.deleted" in actions


async def test_shutdown_marks_running_answers_interrupted(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        chat = await new_chat(client)
    state = await start_in_background(app, owner, chat["id"], "[[mock:slow]] a b c d e f g")
    await asyncio.sleep(0.3)
    await app.state.chat_streams.shutdown()
    row = await message_row(app, state.message_id)
    assert row.status == "failed" and row.error_code == "interrupted"


async def test_startup_marks_orphaned_streaming_messages_failed(
    app_factory: AppFactory, owner: User
) -> None:
    app = await app_factory()
    async with app.state.db.sessionmaker() as db:
        conv = Conversation(user_id=owner.id, title="t", last_message_at=datetime.now(UTC))
        db.add(conv)
        await db.flush()
        msg = Message(
            conversation_id=conv.id,
            user_id=owner.id,
            role="assistant",
            content="half",
            status="streaming",
        )
        db.add(msg)
        await db.commit()
        msg_id = msg.id
    await app_factory()  # a fresh process start runs recovery
    row = await message_row(app, msg_id)
    assert row.status == "failed"
    assert row.error_code == "interrupted"
    assert row.content == "half"
