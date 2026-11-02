"""«Полный доступ» (the owner's decision): a persistent agent the owner picks may use every
enabled tool without approvals until the owner switches it off. Turning it on needs the
password (shared login lockout); everything else — switched-off tools, per-agent "deny",
the kill switch, budgets, audit — still applies, and nobody inherits it."""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update

from app.models import Agent, AuditLog, Task
from app.orchestrator.plan import SubtaskSpec
from app.orchestrator.subagents import create_subagent
from app.providers import mock_provider
from app.services.auth import login_subject_key
from app.services.users import UserService
from app.tools.builtin import files as files_module
from app.tools.policy import Verdict, authorize
from app.tools.registry import catalog, specs_for
from tests.conftest import (
    OWNER_PASSWORD,
    OWNER_USERNAME,
    AppFactory,
    RecordingQueue,
    create_agent,
    csrf_headers,
    drain,
    logged_in_client,
    login,
    make_client,
    run_agent,
)
from tests.test_agent_budgets import budget_of, limit_for, priced_model, set_budget
from tests.test_agents_talk import per_agent
from tests.tools_helpers import approvals, audit_actions, scripted, tool_agent, tool_calls


@pytest.fixture
async def fa_app(app_factory: AppFactory, tmp_path: Path) -> FastAPI:
    app = await app_factory(workspace_root=str(tmp_path / "ws"), login_max_failures=3)
    async with app.state.db.sessionmaker() as db:
        await UserService(db).create_owner(OWNER_USERNAME, OWNER_PASSWORD, "Owner")
    app.state.queue = RecordingQueue()
    return app


async def full_access(
    client: httpx.AsyncClient, agent_id: str, enabled: bool = True, **body: Any
) -> httpx.Response:
    if enabled and "password" not in body:
        body["password"] = OWNER_PASSWORD
    return await client.put(
        f"/api/v1/agents/{agent_id}/full-access",
        json={"enabled": enabled, **body},
        headers=await csrf_headers(client),
    )


async def trusted_agent(client: httpx.AsyncClient, **extra: Any) -> dict[str, Any]:
    """A supervised agent with no tools of its own, then full access."""
    agent = await tool_agent(client, autonomy="supervised", tools=[], **extra)
    resp = await full_access(client, agent["id"])
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


async def task_status(app: FastAPI, task_id: str) -> Task:
    async with app.state.db.sessionmaker() as db:
        task = await db.get(Task, uuid.UUID(task_id))
        assert task is not None
        return task


def ws_files(app: FastAPI, rel: str) -> list[Path]:
    return list(Path(app.state.settings.workspace_root).glob(f"*/{rel}"))


# --- switching it on and off ---------------------------------------------------------------


async def test_granting_needs_the_password_revoking_does_not(fa_app: FastAPI) -> None:
    async with logged_in_client(fa_app) as client:
        agent = await create_agent(client, name="Dev")
        assert agent["full_access"] is False and agent["full_access_since"] is None

        missing = await client.put(
            f"/api/v1/agents/{agent['id']}/full-access",
            json={"enabled": True},
            headers=await csrf_headers(client),
        )
        assert missing.status_code == 422
        assert missing.json()["error"]["code"] == "password_required"
        wrong = await full_access(client, agent["id"], password="wrong")
        assert wrong.status_code == 403 and wrong.json()["error"]["code"] == "invalid_password"
        assert (await client.get(f"/api/v1/agents/{agent['id']}")).json()["full_access"] is False

        granted = await full_access(client, agent["id"])
        assert granted.status_code == 200, granted.text
        body = granted.json()
        assert body["full_access"] is True and body["full_access_since"]
        assert body["autonomy_level"] == "supervised"  # the base level is kept for later
        # Granting again changes nothing (same moment, no second audit row).
        again = await full_access(client, agent["id"])
        assert again.json()["full_access_since"] == body["full_access_since"]

        revoked = await full_access(client, agent["id"], enabled=False)  # no password
        assert revoked.status_code == 200 and revoked.json()["full_access"] is False
        assert revoked.json()["full_access_since"] is None
        assert (await full_access(client, agent["id"], enabled=False)).status_code == 200

        # It is never part of a normal save.
        patch = await client.patch(
            f"/api/v1/agents/{agent['id']}",
            json={"full_access": True},
            headers=await csrf_headers(client),
        )
        assert patch.status_code == 422

    (granted_row,) = await audit_actions(fa_app, "agent.full_access_granted")
    assert granted_row.actor_type == "user" and granted_row.resource_id == agent["id"]
    assert granted_row.details["subject_key"] == login_subject_key(OWNER_USERNAME)
    assert granted_row.details["autonomy"] == "supervised"
    assert "password" not in str(granted_row.details).lower()
    (revoked_row,) = await audit_actions(fa_app, "agent.full_access_revoked")
    assert revoked_row.details["reason"] == "owner" and revoked_row.details["since"]
    (failed,) = await audit_actions(fa_app, "auth.password_confirm_failed")
    assert failed.details["purpose"] == "agent_full_access"


async def test_wrong_passwords_count_toward_the_login_lockout(fa_app: FastAPI) -> None:
    async with logged_in_client(fa_app) as client, make_client(fa_app) as other:
        agent = await create_agent(client, name="Dev")
        assert (await login(other, password="wrong")).status_code == 401
        for _ in range(2):
            assert (await full_access(client, agent["id"], password="wrong")).status_code == 403
        blocked = await full_access(client, agent["id"])  # even the right one is refused now
        assert blocked.status_code == 429
        assert blocked.json()["error"]["code"] == "too_many_attempts"
        assert (await login(other)).status_code == 429  # and so is signing in
        assert (await client.get(f"/api/v1/agents/{agent['id']}")).json()["full_access"] is False
    assert await audit_actions(fa_app, "agent.full_access_granted") == []


async def test_a_correct_password_restarts_the_count(fa_app: FastAPI) -> None:
    async with logged_in_client(fa_app) as client:
        a, b = await create_agent(client, name="A"), await create_agent(client, name="B")
        for _ in range(2):
            assert (await full_access(client, a["id"], password="wrong")).status_code == 403
        assert (await full_access(client, a["id"])).status_code == 200
        for _ in range(2):
            assert (await full_access(client, b["id"], password="wrong")).status_code == 403
        assert (await full_access(client, b["id"])).status_code == 200


async def test_only_persistent_agents_can_have_it(fa_app: FastAPI) -> None:
    async with logged_in_client(fa_app) as client:
        me = (await client.get("/api/v1/auth/me")).json()["user"]
        async with fa_app.state.db.sessionmaker() as db:
            orchestrator = Agent(
                user_id=uuid.UUID(me["id"]), name="Orchestrator", agent_type="orchestrator"
            )
            sub = Agent(user_id=uuid.UUID(me["id"]), name="Sub", agent_type="subagent")
            db.add_all([orchestrator, sub])
            await db.commit()
        for target in (orchestrator, sub):
            resp = await full_access(client, str(target.id))
            assert resp.status_code == 409
            assert resp.json()["error"]["code"] == "full_access_not_allowed"
        assert (await full_access(client, str(uuid.uuid4()))).status_code == 404
    # Refused before the password is checked: no attempt used.
    assert await audit_actions(fa_app, "auth.password_confirm_failed") == []


async def test_removing_the_agent_switches_it_off(fa_app: FastAPI) -> None:
    async with logged_in_client(fa_app) as client:
        agent = await create_agent(client, name="Dev")
        assert (await full_access(client, agent["id"])).status_code == 200
        headers = await csrf_headers(client)
        resp = await client.delete(f"/api/v1/agents/{agent['id']}", headers=headers)
        assert resp.status_code == 204
        restored = await client.post(
            f"/api/v1/agents/{agent['id']}/restore", headers=await csrf_headers(client)
        )
        assert restored.status_code == 200 and restored.json()["full_access"] is False
    (row,) = await audit_actions(fa_app, "agent.full_access_revoked")
    assert row.details["reason"] == "archived"


# --- what it allows -------------------------------------------------------------------------


async def test_write_and_sensitive_tools_run_without_approval(
    fa_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []
    script = scripted(
        ("fs_write", {"path": "old.txt", "content": "bye"}),  # write, not in allowed_tools
        ("fs_delete", {"path": "old.txt"}),  # sensitive
        "Done.",
    )

    def capture(req: Any) -> Any:
        seen.append(req)
        return script(req)

    monkeypatch.setattr(mock_provider, "_handlers", [capture])
    async with logged_in_client(fa_app) as client:
        agent = await trusted_agent(client)
        assert agent["allowed_tools"] == []
        task_id = (await run_agent(client, agent["id"], "Clean up")).json()["task"]["id"]
        await drain(fa_app, fa_app.state.queue)
        pending = (await client.get("/api/v1/approvals?status=pending")).json()

    assert (await task_status(fa_app, task_id)).status == "completed"
    rows = await tool_calls(fa_app, task_id)
    assert [(c.tool_name, c.category, c.decision, c.status) for c in rows] == [
        ("fs_write", "write", "allow", "succeeded"),
        ("fs_delete", "sensitive", "allow", "succeeded"),
    ]
    assert all((c.decision_reason or "").startswith("Full access") for c in rows)
    assert not ws_files(fa_app, "old.txt")
    assert pending == [] and await approvals(fa_app, task_id) == []
    # The model is offered every enabled, available tool, not just an allowed list.
    offered = {t.name for t in seen[0].tools}
    assert {"fs_write", "fs_delete", "fs_read", "memory_save", "work_search"} <= offered
    # Every decision and execution is still audited, marked as done under full access.
    decisions = await audit_actions(fa_app, "tool.authorized")
    executed = await audit_actions(fa_app, "tool.executed")
    assert len(decisions) == len(executed) == 2
    assert all(r.details["full_access"] is True for r in [*decisions, *executed])
    assert all(r.details["autonomy"] == "supervised" for r in decisions)


async def test_switched_off_tools_and_per_agent_exceptions_still_apply(
    fa_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        mock_provider,
        "_handlers",
        [
            scripted(
                ("fs_delete", {"path": "a.txt"}),  # switched off for everyone
                ("fs_write", {"path": "a.txt", "content": "A"}),  # blocked for this agent
                ("fs_list", {"path": "."}),  # the owner wants to approve this one
                "ok",
            )
        ],
    )
    async with logged_in_client(fa_app) as client:
        agent = await trusted_agent(client)
        resp = await client.patch(
            f"/api/v1/agents/{agent['id']}",
            json={"tool_overrides": {"fs_write": "deny", "fs_list": "approve"}},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 200, resp.text
        off = await client.patch(
            "/api/v1/tools/fs_delete", json={"enabled": False}, headers=await csrf_headers(client)
        )
        assert off.status_code == 200, off.text
        task_id = (await run_agent(client, agent["id"], "Try")).json()["task"]["id"]
        await drain(fa_app, fa_app.state.queue)

    rows = await tool_calls(fa_app, task_id)
    assert [(c.tool_name, c.decision, c.status) for c in rows] == [
        ("fs_delete", "deny", "denied"),
        ("fs_write", "deny", "denied"),
        ("fs_list", "require_approval", "awaiting_approval"),
    ]
    assert "turned off" in (rows[0].decision_reason or "")
    assert "blocked this tool" in (rows[1].decision_reason or "")
    assert not ws_files(fa_app, "a.txt")
    assert (await task_status(fa_app, task_id)).status == "waiting_approval"


async def test_switching_it_off_takes_effect_at_the_next_action(
    fa_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = files_module.FsWrite.run

    async def write_then_revoke(self: Any, ctx: Any, args: dict[str, Any]) -> Any:
        out = await original(self, ctx, args)
        async with ctx.sessionmaker() as db:  # the owner switches it off meanwhile
            await db.execute(
                update(Agent).where(Agent.id == ctx.agent.id).values(full_access_since=None)
            )
            await db.commit()
        return out

    monkeypatch.setattr(files_module.FsWrite, "run", write_then_revoke)
    monkeypatch.setattr(
        mock_provider,
        "_handlers",
        [
            scripted(
                ("fs_write", {"path": "a.txt", "content": "A"}),
                ("fs_write", {"path": "b.txt", "content": "B"}),
                "ok",
            )
        ],
    )
    async with logged_in_client(fa_app) as client:
        agent = await trusted_agent(client)
        task_id = (await run_agent(client, agent["id"], "Write")).json()["task"]["id"]
        await drain(fa_app, fa_app.state.queue)
    rows = await tool_calls(fa_app, task_id)
    # Back to its own settings: fs_write is not in its (empty) list of tools.
    assert [(c.tool_name, c.status) for c in rows] == [
        ("fs_write", "succeeded"),
        ("fs_write", "denied"),
    ]
    assert ws_files(fa_app, "a.txt") and not ws_files(fa_app, "b.txt")


# --- what still stops it --------------------------------------------------------------------


async def test_the_kill_switch_still_stops_it(
    fa_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        mock_provider, "_handlers", [scripted(("fs_write", {"path": "x", "content": "x"}), "ok")]
    )
    async with logged_in_client(fa_app) as client:
        agent = await trusted_agent(client)
        task_id = (await run_agent(client, agent["id"], "Write")).json()["task"]["id"]
        stop = await client.post("/api/v1/system/stop-all", headers=await csrf_headers(client))
        assert stop.status_code == 200
        await drain(fa_app, fa_app.state.queue)
        blocked = await run_agent(client, agent["id"], "Again")
        assert blocked.status_code == 409
        assert blocked.json()["error"]["code"] == "engine_stopped"
    assert (await task_status(fa_app, task_id)).status == "cancelled"
    assert await tool_calls(fa_app, task_id) == []
    assert not ws_files(fa_app, "x")


async def test_the_budget_still_stops_it(fa_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async with logged_in_client(fa_app) as client:
        await priced_model(client)
        agent = await create_agent(client, name="Spender")
        assert (await full_access(client, agent["id"])).status_code == 200
        assert (await run_agent(client, agent["id"], "First", "one two")).status_code == 200
        await drain(fa_app, fa_app.state.queue)
        spent = Decimal((await budget_of(client, agent["id"]))["spent_usd"])
        # A limit at about half of what it already spent: over budget.
        assert (await set_budget(client, agent["id"], limit_for(spent, 2.0))).status_code == 200
        monkeypatch.setattr(
            mock_provider,
            "_handlers",
            [scripted(("fs_write", {"path": "x", "content": "x"}), "ok")],
        )
        task_id = (await run_agent(client, agent["id"], "Second", "three")).json()["task"]["id"]
        await drain(fa_app, fa_app.state.queue)
    task = await task_status(fa_app, task_id)
    assert task.status == "failed" and task.error_code == "agent_budget_exceeded"
    assert await tool_calls(fa_app, task_id) == []


# --- nobody inherits it ---------------------------------------------------------------------


async def test_subagents_never_inherit_it(fa_app: FastAPI) -> None:
    async with logged_in_client(fa_app) as client:
        parent = await trusted_agent(client)
        # The parent's own list (its floor) is what a subagent can get at most.
        resp = await client.patch(
            f"/api/v1/agents/{parent['id']}",
            json={"allowed_tools": ["fs_read"]},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 200 and resp.json()["full_access"] is True
    settings = fa_app.state.settings
    async with fa_app.state.db.sessionmaker() as db:
        row = await db.get(Agent, uuid.UUID(parent["id"]))
        assert row is not None and row.full_access
        child = await create_subagent(
            db,
            parent=row,
            root_run=uuid.uuid4(),
            spec=SubtaskSpec(key="a", title="A", tools=["fs_read", "fs_write", "fs_delete"]),
            settings=settings,
        )
        await db.commit()
        entries = await catalog(db, row.user_id, settings)
    assert child.full_access is False and child.full_access_since is None
    assert child.allowed_tools == ["fs_read"]
    assert child.autonomy_level == "supervised"
    assert {s.name for s in specs_for(child, entries)} == {"fs_read", "work_search", "work_read"}
    # Even a subagent row with the column set is not trusted (only persistent agents are).
    child.full_access_since = row.full_access_since
    assert child.full_access is False
    from tests.test_tool_policy import ctx as tool_ctx

    for name in ("fs_write", "fs_delete"):
        decision = await authorize(
            agent=child, name=name, entry=entries[name], args={"path": "x"}, ctx=tool_ctx(child)
        )
        assert decision.verdict == Verdict.DENY


async def test_an_asked_agent_acts_under_its_own_settings(
    fa_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        mock_provider,
        "_handlers",
        [
            per_agent(
                {
                    "Alice": [("agent_ask", {"agent": "Bob", "request": "Write a.txt"}), "done"],
                    "Bob": [("fs_write", {"path": "a.txt", "content": "A"}), "written"],
                }
            )
        ],
    )
    async with logged_in_client(fa_app) as client:
        alice = await trusted_agent(client, name="Alice")  # full access, no tools listed
        bob = await create_agent(
            client, name="Bob", autonomy_level="supervised", allowed_tools=["fs_write"]
        )
        task_id = (await run_agent(client, alice["id"], "Ask Bob")).json()["task"]["id"]
        await drain(fa_app, fa_app.state.queue)
        pending = (await client.get("/api/v1/approvals?status=pending")).json()

    # Alice's question ran straight away; Bob's write waits for the owner (Bob is supervised).
    (ask,) = await tool_calls(fa_app, task_id)
    assert (ask.tool_name, ask.decision) == ("agent_ask", "allow")
    assert len(pending) == 1
    assert pending[0]["agent_id"] == bob["id"] and pending[0]["tool_name"] == "fs_write"
    assert not ws_files(fa_app, "a.txt")
    async with fa_app.state.db.sessionmaker() as db:
        bob_decisions = (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.action == "tool.authorized", AuditLog.actor_id == uuid.UUID(bob["id"])
                )
            )
        ).scalars()
        assert all("full_access" not in r.details for r in bob_decisions)
