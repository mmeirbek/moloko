"""«Одобрить и больше не спрашивать»: after the owner approves an action that way, the agent
does that kind of action without asking — until the owner takes it back."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI

from app.models.agent import Agent
from app.providers import mock_provider
from tests.conftest import csrf_headers, drain, logged_in_client, run_agent
from tests.test_tools_engine import task_of, tool_app, ws_file  # noqa: F401 — fixture
from tests.tools_helpers import scripted, tool_agent


def test_what_a_command_approval_covers() -> None:
    from app.tools.standing import covering, programs

    assert programs('python3 -c "\ndef L(h):\n  return 1;\n"') == ["python3"]
    assert programs("cd /w && npm i | tee log") == ["cd", "npm", "tee"]
    assert programs("python3 x.py\nrm -rf .") == ["python3", "rm"]
    for unsafe in ("echo $(rm -rf .)", "echo `id`", "FOO=1 python3 x.py", "(rm x)", 'echo "x'):
        assert programs(unsafe) is None, unsafe

    agent = Agent(
        permissions={"always": [{"id": "r1", "tool": "terminal_run", "scope": "python3"}]}
    )
    assert covering(agent, "terminal_run", {"command": "python3 check.py"}) is not None
    # every program in the command must be allowed, and substitutions always ask
    assert covering(agent, "terminal_run", {"command": "python3 a.py && rm -rf ."}) is None
    assert covering(agent, "terminal_run", {"command": 'python3 -c "$(cat x)"'}) is None
    assert covering(agent, "fs_write", {"path": "a"}) is None
    repo = Agent(
        permissions={"always": [{"id": "r2", "tool": "github_write_file", "scope": "me/a"}]}
    )
    assert covering(repo, "github_write_file", {"repo": "Me/A", "path": "x"}) is not None
    assert covering(repo, "github_write_file", {"repo": "me/b", "path": "x"}) is None


async def test_approve_and_dont_ask_again_then_take_it_back(
    tool_app: FastAPI,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mock_provider,
        "_handlers",
        [
            scripted(
                ("fs_write", {"path": "a.txt", "content": "A"}),
                ("fs_write", {"path": "b.txt", "content": "B"}),
                "done",
            )
        ],
    )
    queue = tool_app.state.queue
    async with logged_in_client(tool_app) as client:
        headers = await csrf_headers(client)
        agent = await tool_agent(client, autonomy="supervised", tools=["fs_write"])
        first = (await run_agent(client, agent["id"], "Two files")).json()["task"]["id"]
        await drain(tool_app, queue)
        pending = (await client.get("/api/v1/approvals?status=pending")).json()
        assert len(pending) == 1 and pending[0]["always"] == [""]  # the whole tool

        resp = await client.post(
            f"/api/v1/approvals/{pending[0]['id']}/approve", json={"always": True}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        await drain(tool_app, queue)
        # the second, different write did not ask
        assert (await task_of(tool_app, first)).status == "completed"
        assert ws_file(tool_app, "a.txt") and ws_file(tool_app, "b.txt")
        rules = (await client.get(f"/api/v1/agents/{agent['id']}")).json()["permissions"]["always"]
        assert [(r["tool"], r["scope"]) for r in rules] == [("fs_write", "")]

        # taken back: the next write asks again
        gone = await client.delete(
            f"/api/v1/agents/{agent['id']}/standing-approvals/{rules[0]['id']}", headers=headers
        )
        assert gone.status_code == 200
        assert gone.json()["permissions"].get("always") == []
        second = (await run_agent(client, agent["id"], "Again")).json()["task"]["id"]
        await drain(tool_app, queue)
        assert (await task_of(tool_app, second)).status == "waiting_approval"
        audit = (await client.get("/api/v1/audit?limit=100")).json()["items"]
        actions = {row["action"] for row in audit}
        assert {"agent.standing_approval_added", "agent.standing_approval_removed"} <= actions


async def test_approve_every_use_cannot_be_turned_into_always(
    tool_app: FastAPI,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mock_provider,
        "_handlers",
        [scripted(("fs_write", {"path": "a.txt", "content": "A"}), "ok")],
    )
    async with logged_in_client(tool_app) as client:
        headers = await csrf_headers(client)
        extra: dict[str, Any] = {"tool_overrides": {"fs_write": "approve"}}
        agent = await tool_agent(client, autonomy="balanced", tools=["fs_write"], **extra)
        await run_agent(client, agent["id"], "One file")
        await drain(tool_app, tool_app.state.queue)
        pending = (await client.get("/api/v1/approvals?status=pending")).json()
        assert pending[0]["always"] is None
        resp = await client.post(
            f"/api/v1/approvals/{pending[0]['id']}/approve", json={"always": True}, headers=headers
        )
        assert resp.status_code == 409 and resp.json()["error"]["code"] == "standing_not_offered"
        still = (await client.get("/api/v1/approvals?status=pending")).json()
        assert len(still) == 1  # nothing was decided
