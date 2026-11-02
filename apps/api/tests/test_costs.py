"""Costs: the usage ledger, summaries per agent/model/day, and the monthly budget."""

from __future__ import annotations

from decimal import Decimal

from fastapi import FastAPI
from sqlalchemy import select

from app.models import AgentEvent, User
from app.services.usage import thresholds_crossed
from tests.conftest import (
    RecordingQueue,
    add_mock_model,
    create_agent,
    csrf_headers,
    drain,
    logged_in_client,
    run_agent,
)
from tests.test_chat_api import new_chat
from tests.test_chat_attachments import send


def test_each_alert_fires_once() -> None:
    assert thresholds_crossed(Decimal("5"), None, 80, []) == []
    assert thresholds_crossed(Decimal("7"), Decimal("10"), 80, []) == []
    assert thresholds_crossed(Decimal("8"), Decimal("10"), 80, []) == [80]
    assert thresholds_crossed(Decimal("8"), Decimal("10"), 80, [80]) == []
    assert thresholds_crossed(Decimal("12"), Decimal("10"), 80, [80]) == [100]
    assert thresholds_crossed(Decimal("12"), Decimal("10"), 80, []) == [80, 100]


async def test_costs_per_agent_and_model_and_the_budget(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        model = await add_mock_model(client)
        resp = await client.patch(
            f"/api/v1/models/{model['id']}",
            json={"input_price_per_mtok": "1000", "output_price_per_mtok": "2000"},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 200, resp.text

        chat = await new_chat(client)
        status, _ = await send(client, chat["id"], "Hello there, how are you", [])
        assert status == 200
        agent = await create_agent(client, name="Counter")
        assert (await run_agent(client, agent["id"], "Count", "one two three")).status_code == 200
        await drain(app, queue)

        costs = (await client.get("/api/v1/costs")).json()
        assert costs["calls"] >= 2 and Decimal(costs["spent_usd"]) > 0
        sources = {row["source"]: row for row in costs["by_agent"]}
        assert sources["agent"]["name"] == "Counter" and sources["agent"]["calls"] >= 1
        assert sources["chat"]["calls"] == 1
        assert [m["model"] for m in costs["by_model"]] == [model["model"]]
        assert costs["by_day"] and costs["budget"]["monthly_limit_usd"] is None

        # A limit below what is spent: one warning for 80 % and 100 %, then a hard stop.
        resp = await client.put(
            "/api/v1/costs/budget",
            json={"monthly_limit_usd": "0.01", "warn_percent": 80, "hard_stop": True},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["percent"] > 100
        async with app.state.db.sessionmaker() as db:
            warnings = (
                (await db.execute(select(AgentEvent).where(AgentEvent.type == "budget.warning")))
                .scalars()
                .all()
            )
        assert len(warnings) == 1 and warnings[0].payload["percent"] == 100

        status, body = await send(client, chat["id"], "One more?", [])
        assert status == 409 and "budget_exceeded" in body
        assert (await run_agent(client, agent["id"], "Again", "four five")).status_code == 200
        await drain(app, queue)
        tasks = (await client.get(f"/api/v1/tasks?agent_id={agent['id']}&status=all")).json()
        assert tasks["items"][0]["error_code"] == "budget_exceeded"

        # Turning the stop off lets work continue (warnings are not repeated this month).
        await client.put(
            "/api/v1/costs/budget",
            json={"monthly_limit_usd": "0.01", "hard_stop": False},
            headers=await csrf_headers(client),
        )
        status, _ = await send(client, chat["id"], "Now?", [])
        assert status == 200
        async with app.state.db.sessionmaker() as db:
            count = len(
                (await db.execute(select(AgentEvent).where(AgentEvent.type == "budget.warning")))
                .scalars()
                .all()
            )
        assert count == 1
