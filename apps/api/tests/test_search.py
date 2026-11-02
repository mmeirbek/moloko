"""Semantic search (pgvector) over memories and files, for the owner and for agents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.models import User
from app.providers import mock_provider
from app.search.index import chunk_text, index_user
from app.services.users import UserService
from tests.conftest import (
    OWNER_PASSWORD,
    OWNER_USERNAME,
    AppFactory,
    RecordingQueue,
    add_mock_model,
    create_agent,
    csrf_headers,
    drain,
    logged_in_client,
    run_agent,
)
from tests.test_memory import remember
from tests.tools_helpers import scripted, tool_agent


def test_chunks_follow_paragraphs_and_size() -> None:
    body = "First paragraph.\n\nSecond one is here.\n\n" + "word " * 400
    chunks = chunk_text(body, 300)
    assert chunks[0].startswith("First paragraph.\n\nSecond one")
    assert all(len(c) <= 300 for c in chunks)
    assert chunk_text("", 300) == []


async def reindex(app: FastAPI, user: User) -> int:
    async with app.state.db.sessionmaker() as db:
        return await index_user(db, app.state.gateway, app.state.settings, user.id)


async def test_owner_finds_notes_by_meaning_and_by_words(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        note = (
            await remember(client, title="Молоко", content="Молоко на ферме: цена 90 рублей.")
        ).json()
        await remember(client, title="Garden", content="Tomatoes need water every day.")
        assert await reindex(app, owner) == 2
        assert await reindex(app, owner) == 0  # nothing changed

        found = (await client.get("/api/v1/search", params={"q": "dairy cost"})).json()["hits"]
        assert found[0]["source_id"] == note["id"] and found[0]["mode"] == "semantic"
        status = (await client.get("/api/v1/search/status")).json()
        assert status["sources"] == 2 and status["with_vectors"] == status["chunks"]

        # Without semantic search the words still work.
        await client.put(
            "/api/v1/ai/settings",
            json={"semantic_search": False},
            headers=await csrf_headers(client),
        )
        assert await reindex(app, owner) == 2  # re-indexed without vectors
        hits = (await client.get("/api/v1/search", params={"q": "tomatoes"})).json()["hits"]
        assert hits[0]["title"] == "Garden" and hits[0]["mode"] == "words"

        # A forgotten note leaves the index.
        await client.delete(f"/api/v1/memories/{note['id']}", headers=await csrf_headers(client))
        await reindex(app, owner)
        hits = (await client.get("/api/v1/search", params={"q": "молоко"})).json()["hits"]
        assert [h["source_id"] for h in hits] == []


@pytest.fixture
async def tool_app(app_factory: AppFactory, tmp_path: Path) -> FastAPI:
    app = await app_factory(workspace_root=str(tmp_path / "ws"))
    async with app.state.db.sessionmaker() as db:
        await UserService(db).create_owner(OWNER_USERNAME, OWNER_PASSWORD, "Owner")
    app.state.queue = RecordingQueue()
    return app


async def test_agents_search_only_their_own_memory(
    tool_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []
    script = scripted(("knowledge_search", {"query": "milk price"}), "Done.")

    def capture(req: Any) -> Any:
        seen.append(req)
        return script(req)

    async with logged_in_client(tool_app) as client:
        agent = await tool_agent(client, tools=["knowledge_search"])
        other = await create_agent(client, name="Other")
        await remember(
            client,
            memory_type="agent",
            agent_id=agent["id"],
            title="Mine",
            content="Milk costs 90.",
        )
        await remember(
            client,
            memory_type="agent",
            agent_id=other["id"],
            title="Secret",
            content="Milk price is secret.",
        )
        async with tool_app.state.db.sessionmaker() as db:
            owner = (await db.execute(select(User))).scalar_one()
        await reindex(tool_app, owner)
        monkeypatch.setattr(mock_provider, "_handlers", [capture])
        task_id = (await run_agent(client, agent["id"], "Find the price")).json()["task"]["id"]
        await drain(tool_app, tool_app.state.queue)
        detail = (await client.get(f"/api/v1/tasks/{task_id}")).json()
    assert detail["task"]["status"] == "completed"
    tool_result = next(m.content for m in seen[-1].messages if m.role == "tool")
    assert 'title="Mine"' in tool_result and "Secret" not in tool_result
    assert 'trust="untrusted"' in tool_result
