"""A monthly budget per agent: the warning, the hard stop, subagents counting against the
Orchestrator, the agent page's numbers and the per-agent rows on the Costs page."""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from app.models import AgentEvent, AuditLog, UsageRecord, User
from app.push.dispatcher import TITLES, notice_for
from tests.conftest import (
    RecordingQueue,
    add_mock_model,
    create_agent,
    csrf_headers,
    drain,
    logged_in_client,
    run_agent,
)
from tests.test_orchestrator import start_run, tree


async def priced_model(client: httpx.AsyncClient) -> dict[str, Any]:
    """The mock model at $1 per token, so every call costs several dollars."""
    model = await add_mock_model(client)
    resp = await client.patch(
        f"/api/v1/models/{model['id']}",
        json={"input_price_per_mtok": "1000000", "output_price_per_mtok": "1000000"},
        headers=await csrf_headers(client),
    )
    assert resp.status_code == 200, resp.text
    return model


async def set_budget(client: httpx.AsyncClient, agent_id: str, value: str | None) -> httpx.Response:
    return await client.patch(
        f"/api/v1/agents/{agent_id}",
        json={"monthly_budget_usd": value},
        headers=await csrf_headers(client),
    )


async def budget_of(client: httpx.AsyncClient, agent_id: str) -> dict[str, Any]:
    resp = await client.get(f"/api/v1/agents/{agent_id}/budget")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def warnings(app: FastAPI) -> list[dict[str, Any]]:
    async with app.state.db.sessionmaker() as db:
        rows = await db.execute(
            select(AgentEvent).where(AgentEvent.type == "budget.warning").order_by(AgentEvent.seq)
        )
        return [e.payload for e in rows.scalars()]


def limit_for(spent: Decimal, share: float) -> str:
    """A limit (whole cents) at which ``spent`` is about ``share`` of it."""
    return f"{math.ceil(float(spent) / share * 100) / 100:.2f}"


async def last_task(client: httpx.AsyncClient, agent_id: str) -> dict[str, Any]:
    tasks = (await client.get(f"/api/v1/tasks?agent_id={agent_id}&status=all")).json()
    return tasks["items"][0]


async def test_warning_then_hard_stop_at_the_agents_limit(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await priced_model(client)
        agent = await create_agent(client, name="Spender")
        other = await create_agent(client, name="Free")
        assert (await run_agent(client, agent["id"], "First", "one two three")).status_code == 200
        await drain(app, queue)
        first = await budget_of(client, agent["id"])
        spent = Decimal(first["spent_usd"])
        assert spent > 0 and first["monthly_budget_usd"] is None and first["percent"] is None
        assert first["budget_agent_id"] == agent["id"] and first["warn_percent"] == 80
        assert await warnings(app) == []  # no limit, no warnings

        # A limit at which this month's spending is ~90 %: one warning (80 %), work continues.
        resp = await set_budget(client, agent["id"], limit_for(spent, 0.9))
        assert resp.status_code == 200, resp.text
        assert resp.json()["monthly_budget_usd"] == limit_for(spent, 0.9)
        sent = await warnings(app)
        assert len(sent) == 1
        assert sent[0]["scope"] == "agent" and sent[0]["percent"] == 80
        assert sent[0]["agent_id"] == agent["id"] and sent[0]["agent_name"] == "Spender"
        status = await budget_of(client, agent["id"])
        assert 80 <= status["percent"] < 100 and status["exceeded"] is False

        # The next run may start (still under the limit) and crosses 100 %: a second warning.
        assert (await run_agent(client, agent["id"], "Second", "four five")).status_code == 200
        await drain(app, queue)
        assert (await last_task(client, agent["id"]))["status"] == "completed"
        sent = await warnings(app)
        assert [w["percent"] for w in sent] == [80, 100]
        assert (await budget_of(client, agent["id"]))["exceeded"] is True

        # Over the limit: the agent's new model calls are refused, the task fails readably.
        assert (await run_agent(client, agent["id"], "Third", "six")).status_code == 200
        await drain(app, queue)
        failed = await last_task(client, agent["id"])
        assert failed["status"] == "failed"
        assert failed["error_code"] == "agent_budget_exceeded"
        assert "«Spender»" in failed["error_message"]
        assert len(await warnings(app)) == 2  # not repeated

        # Other agents are not affected (no global limit set).
        assert (await run_agent(client, other["id"], "Other", "seven")).status_code == 200
        await drain(app, queue)
        assert (await last_task(client, other["id"]))["status"] == "completed"

        # A new limit starts the alerts afresh; removing it lets the agent work again.
        status = await budget_of(client, agent["id"])
        resp = await set_budget(client, agent["id"], limit_for(Decimal(status["spent_usd"]), 0.85))
        assert resp.status_code == 200
        assert [w["percent"] for w in await warnings(app)] == [80, 100, 80]
        assert (await set_budget(client, agent["id"], None)).json()["monthly_budget_usd"] is None
        assert (await run_agent(client, agent["id"], "Fourth", "eight")).status_code == 200
        await drain(app, queue)
        assert (await last_task(client, agent["id"]))["status"] == "completed"

    async with app.state.db.sessionmaker() as db:
        updates = (
            (
                await db.execute(
                    select(AuditLog)
                    .where(
                        AuditLog.action == "agent.updated",
                        AuditLog.resource_id == agent["id"],
                    )
                    .order_by(AuditLog.created_at)
                )
            )
            .scalars()
            .all()
        )
    assert [u.details["monthly_budget_usd"]["new"] for u in updates][-1] is None
    assert all("monthly_budget_usd" in u.details["changed"] for u in updates)


async def test_subagents_count_against_the_orchestrators_budget(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await priced_model(client)
        started = await start_run(client, "Report", "[[mock:plan:2]] one two")
        await drain(app, queue)
        t = await tree(client, started["run"]["id"])
        assert t["task"]["status"] == "completed"
        orchestrator_id = t["run"]["agent_id"]
        subagent_ids = [a["id"] for a in t["subagents"]]
        assert len(subagent_ids) == 2

        async with app.state.db.sessionmaker() as db:
            rows = (await db.execute(select(UsageRecord))).scalars().all()
        assert {str(r.agent_id) for r in rows} >= {orchestrator_id, *subagent_ids}
        assert {str(r.budget_agent_id) for r in rows} == {orchestrator_id}

        sub_budget = await budget_of(client, subagent_ids[0])
        assert sub_budget["budget_agent_id"] == orchestrator_id
        own = await budget_of(client, orchestrator_id)
        assert Decimal(own["spent_usd"]) == sum(Decimal(str(r.cost_usd)) for r in rows)
        assert sub_budget["spent_usd"] == own["spent_usd"]

        # Subagents have no budget of their own (and they leave the office after the run).
        assert sub_budget["monthly_budget_usd"] == own["monthly_budget_usd"]
        assert (await set_budget(client, subagent_ids[0], "5.00")).status_code == 404

        # The Costs page: one row for the Orchestrator, its subagents' share and its limit.
        double = limit_for(Decimal(own["spent_usd"]), 0.5)
        assert (await set_budget(client, orchestrator_id, double)).status_code == 200
        costs = (await client.get("/api/v1/costs")).json()
        rows_by_id = {r["agent_id"]: r for r in costs["by_agent"]}
        assert set(rows_by_id) == {orchestrator_id}
        row = rows_by_id[orchestrator_id]
        assert row["source"] == "orchestrator"
        assert Decimal(row["cost_usd"]) == Decimal(own["spent_usd"])
        assert 0 < Decimal(row["subagents_cost_usd"]) < Decimal(row["cost_usd"])
        assert row["monthly_budget_usd"] is not None and 45 < row["percent"] < 55

        # Once the Orchestrator's budget is used up, its next run fails at planning.
        assert (await set_budget(client, orchestrator_id, "1.00")).status_code == 200
        again = await start_run(client, "More", "[[mock:plan:2]]")
        await drain(app, queue)
        t2 = await tree(client, again["run"]["id"])
        assert t2["task"]["status"] == "failed"
        assert t2["task"]["error_code"] == "agent_budget_exceeded"
        assert t2["subtasks"] == []


async def test_a_subagent_stops_when_the_orchestrators_budget_runs_out(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    """The Orchestrator's own planning call fits; its subagents push it over the limit."""
    async with logged_in_client(app) as client:
        await priced_model(client)
        agents = (await client.get("/api/v1/agents")).json()
        orchestrator = next((a for a in agents if a["agent_type"] == "orchestrator"), None)
        if orchestrator is None:  # created on the first run
            await start_run(client, "Warm up")
            await drain(app, queue)
            agents = (await client.get("/api/v1/agents")).json()
            orchestrator = next(a for a in agents if a["agent_type"] == "orchestrator")
        spent = Decimal((await budget_of(client, orchestrator["id"]))["spent_usd"])
        # Room for the plan (20 tokens = $20) but not for both subagents and the synthesis.
        assert (await set_budget(client, orchestrator["id"], str(spent + 25))).status_code == 200
        started = await start_run(client, "Big", "[[mock:chain]] [[mock:plan:3]]")
        await drain(app, queue)
        t = await tree(client, started["run"]["id"])
    codes = [s["error_code"] for s in t["subtasks"] if s["status"] == "failed"]
    assert "agent_budget_exceeded" in codes
    assert t["task"]["status"] == "failed"


async def test_budget_validation(app: FastAPI, owner: User, queue: RecordingQueue) -> None:
    async with logged_in_client(app) as client:
        for bad in ("0", "-1", "1.234", "abc", "2000000"):
            resp = await client.post(
                "/api/v1/agents",
                json={"name": f"Bad {bad}", "monthly_budget_usd": bad},
                headers=await csrf_headers(client),
            )
            assert resp.status_code == 422, bad
        agent = await create_agent(client, name="Fine", monthly_budget_usd="12.5")
        assert agent["monthly_budget_usd"] == "12.50"
        status = await budget_of(client, agent["id"])
        assert status["spent_usd"] == "0" and status["percent"] == 0.0
        assert status["month"] == datetime.now(UTC).strftime("%Y-%m")
        missing = await client.get(f"/api/v1/agents/{uuid.uuid4()}/budget")
        assert missing.status_code == 404


def test_agent_budget_push_notice() -> None:
    now = datetime.now(UTC)
    agent_id = str(uuid.uuid4())
    event = AgentEvent(
        user_id=uuid.uuid4(),
        type="budget.warning",
        agent_id=uuid.UUID(agent_id),
        payload={
            "scope": "agent",
            "agent_id": agent_id,
            "agent_name": "Spender",
            "month": "2026-11",
            "percent": 80,
            "spent_usd": "4.00",
            "limit_usd": "5.00",
        },
        created_at=now,
    )
    notice = notice_for(event, now)
    assert notice is not None and notice.kind == "budget"
    assert notice.key == f"budget:2026-11:{agent_id}:80"
    assert notice.url == f"/office/agents/{agent_id}"
    title = TITLES["ru"][notice.title].format(percent=notice.percent, name=notice.name)
    assert title == "«Spender»: 80% бюджета агента на месяц"
