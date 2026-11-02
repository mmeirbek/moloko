"""A reply cut off by the output limit is never executed: the agent is told to continue in
smaller parts, and a model that keeps getting cut off stops the task with a clear reason
(instead of "finished without producing a result")."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI

from app.providers import mock_provider
from app.providers.base import ChatRequest, ChatResult
from app.providers.base import ToolCall as ModelToolCall
from tests.conftest import drain, logged_in_client, run_agent
from tests.test_tools_engine import task_of, tool_app, ws_file  # noqa: F401 — fixture
from tests.tools_helpers import tool_agent, tool_calls

HALF_WRITTEN = ModelToolCall(
    "call_0", "fs_write", {"path": "big.tsx", "content": "export const A ="}
)


async def test_a_cut_off_reply_is_not_run_and_the_agent_continues(
    tool_app: FastAPI,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[ChatRequest] = []

    def model(req: ChatRequest) -> ChatResult:
        seen.append(req)
        if len(seen) == 1:  # the first reply hits the limit in the middle of a file
            return ChatResult(text="", tool_calls=(HALF_WRITTEN,), stop_reason="max_tokens")
        return ChatResult(text="Done in smaller parts.", stop_reason="end_turn")

    monkeypatch.setattr(mock_provider, "_handlers", [model])
    async with logged_in_client(tool_app) as client:
        agent = await tool_agent(client, tools=["fs_write"])
        task_id = (await run_agent(client, agent["id"], "Redesign the page")).json()["task"]["id"]
        await drain(tool_app, tool_app.state.queue)

    task = await task_of(tool_app, task_id)
    assert task.status == "completed" and task.result == "Done in smaller parts."
    assert await tool_calls(tool_app, task_id) == []  # the half-written call never ran
    assert not ws_file(tool_app, "big.tsx")
    # the agent was given room (16 000 tokens by default) and told what happened
    assert seen[0].max_tokens == tool_app.state.settings.agent_max_output_tokens == 16_000
    note = seen[1].messages[-1]
    assert note.role == "user" and "cut off at the output limit" in note.content


async def test_a_model_that_keeps_getting_cut_off_stops_with_a_reason(
    tool_app: FastAPI,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Any] = []

    def model(req: ChatRequest) -> ChatResult:
        calls.append(req)
        return ChatResult(text="Here is the whole file: …", stop_reason="length")  # OpenAI's word

    monkeypatch.setattr(mock_provider, "_handlers", [model])
    async with logged_in_client(tool_app) as client:
        agent = await tool_agent(client, tools=["fs_write"])
        task_id = (await run_agent(client, agent["id"], "Write everything at once")).json()["task"][
            "id"
        ]
        await drain(tool_app, tool_app.state.queue)

    task = await task_of(tool_app, task_id)
    assert task.status == "failed" and task.error_code == "output_truncated"
    # AGENT_MAX_CUT_OFFS (3) continuations, then the fourth cut-off reply stops it
    assert len(calls) == tool_app.state.settings.agent_max_cut_offs + 1 == 4
