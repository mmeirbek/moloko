"""Scheduled tasks: recurrence math, the API, and the worker's due-run pass."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import jsonschema
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, text

from app.events.bus import envelope
from app.models import AgentEvent, AuditLog, Schedule, Task, User
from app.schedules.recurrence import RecurrenceError, build_rule, next_after, upcoming
from app.services.schedules import run_due
from tests.conftest import (
    RecordingQueue,
    add_mock_model,
    create_agent,
    csrf_headers,
    logged_in_client,
    run_agent,
)

ALMATY = "Asia/Almaty"
BERLIN = "Europe/Berlin"
SCHEMAS = Path(__file__).resolve().parents[3] / "packages" / "agent-contracts" / "schemas"


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def local(moment: datetime, zone: str) -> datetime:
    return moment.astimezone(ZoneInfo(zone))


# --- recurrence math (no database) -----------------------------------------------------------


def test_daily_in_a_zone_without_dst() -> None:
    rule = build_rule(kind="daily", timezone=ALMATY, time_of_day="08:00")
    start = datetime(2026, 11, 2, 7, 59, tzinfo=ZoneInfo(ALMATY))
    first = next_after(rule, start)
    assert first is not None
    assert local(first, ALMATY).replace(tzinfo=None) == datetime(2026, 11, 2, 8, 0)
    # exactly at the run time → the next day (strictly after)
    second = next_after(rule, first)
    assert second is not None
    assert local(second, ALMATY).replace(tzinfo=None) == datetime(2026, 11, 3, 8, 0)
    # no DST: the same UTC offset all year
    runs = upcoming(rule, utc(2026, 1, 1), 365)
    assert len({local(r, ALMATY).utcoffset() for r in runs}) == 1
    assert {local(r, ALMATY).strftime("%H:%M") for r in runs} == {"08:00"}


def test_weekdays_skip_the_weekend() -> None:
    rule = build_rule(kind="weekly", timezone=ALMATY, time_of_day="08:00", weekdays=[5, 1, 2, 3, 4])
    assert rule.weekdays == (1, 2, 3, 4, 5)
    friday_noon = datetime(2026, 11, 6, 12, 0, tzinfo=ZoneInfo(ALMATY))
    nxt = next_after(rule, friday_noon)
    assert nxt is not None
    assert local(nxt, ALMATY).replace(tzinfo=None) == datetime(2026, 11, 9, 8, 0)  # Monday


def test_monthly_uses_the_last_day_of_short_months() -> None:
    rule = build_rule(kind="monthly", timezone=ALMATY, time_of_day="09:30", day_of_month=31)
    runs = upcoming(rule, datetime(2027, 1, 31, 10, 0, tzinfo=ZoneInfo(ALMATY)), 3)
    assert [local(r, ALMATY).date().isoformat() for r in runs] == [
        "2027-02-28",
        "2027-03-31",
        "2027-04-30",
    ]
    leap = next_after(rule, datetime(2028, 2, 1, tzinfo=ZoneInfo(ALMATY)))
    assert leap is not None and local(leap, ALMATY).date().isoformat() == "2028-02-29"


def test_every_n_hours_repeats_the_same_times_every_day() -> None:
    rule = build_rule(kind="hourly", timezone=ALMATY, time_of_day="08:15", interval_hours=6)
    runs = upcoming(rule, datetime(2026, 11, 2, 9, 0, tzinfo=ZoneInfo(ALMATY)), 5)
    assert [local(r, ALMATY).strftime("%d %H:%M") for r in runs] == [
        "02 14:15",
        "02 20:15",
        "03 02:15",
        "03 08:15",
        "03 14:15",
    ]


def test_once_reads_a_local_time_in_the_schedules_zone() -> None:
    rule = build_rule(kind="once", timezone=ALMATY, run_at=datetime(2026, 11, 3, 15, 0))
    assert rule.run_at is not None
    assert local(rule.run_at, ALMATY).replace(tzinfo=None) == datetime(2026, 11, 3, 15, 0)
    assert next_after(rule, rule.run_at - timedelta(seconds=1)) == rule.run_at
    assert next_after(rule, rule.run_at) is None
    assert upcoming(rule, rule.run_at - timedelta(days=1), 3) == [rule.run_at]


def test_daily_follows_the_wall_clock_across_dst() -> None:
    rule = build_rule(kind="daily", timezone=BERLIN, time_of_day="08:00")
    runs = upcoming(rule, utc(2026, 3, 27, 12), 3)  # spring forward on Sunday 2026-03-29
    assert [r.isoformat() for r in runs] == [
        "2026-03-28T07:00:00+00:00",  # CET, UTC+1
        "2026-03-29T06:00:00+00:00",  # CEST, UTC+2
        "2026-03-30T06:00:00+00:00",
    ]
    autumn = upcoming(rule, utc(2026, 10, 24, 12), 2)  # fall back on Sunday 2026-10-25
    assert [r.isoformat() for r in autumn] == [
        "2026-10-25T07:00:00+00:00",
        "2026-10-26T07:00:00+00:00",
    ]


def test_dst_gap_and_repeated_hour() -> None:
    # 02:30 does not exist on 2026-03-29 in Berlin: it runs at the shifted time (03:30 CEST).
    rule = build_rule(kind="daily", timezone=BERLIN, time_of_day="02:30")
    gap = next_after(rule, utc(2026, 3, 28, 12))
    assert gap == utc(2026, 3, 29, 1, 30)
    assert local(gap, BERLIN).strftime("%H:%M") == "03:30"
    # 02:30 happens twice on 2026-10-25: it runs once, the first time (CEST).
    first = next_after(rule, utc(2026, 10, 24, 12))
    assert first == utc(2026, 10, 25, 0, 30)
    assert next_after(rule, first) == utc(2026, 10, 26, 1, 30)


A = {"timezone": ALMATY}
AT8 = {"timezone": ALMATY, "time_of_day": "08:00"}


@pytest.mark.parametrize(
    ("kwargs", "code", "field"),
    [
        ({**AT8, "kind": "daily", "timezone": "Mars/Olympus"}, "invalid_timezone", "timezone"),
        ({**AT8, "kind": "daily", "timezone": "../etc/passwd"}, "invalid_timezone", "timezone"),
        ({**A, "kind": "daily"}, "invalid_recurrence", "time"),
        ({**AT8, "kind": "weekly"}, "invalid_recurrence", "weekdays"),
        ({**AT8, "kind": "monthly"}, "invalid_recurrence", "day_of_month"),
        ({**A, "kind": "hourly", "interval_hours": 5}, "invalid_recurrence", "interval_hours"),
        (
            {**A, "kind": "hourly", "interval_hours": 1, "min_interval_minutes": 120},
            "interval_too_short",
            "interval_hours",
        ),
        ({**A, "kind": "once"}, "invalid_recurrence", "run_at"),
    ],
)
def test_invalid_rules_name_the_field(kwargs: dict[str, Any], code: str, field: str) -> None:
    with pytest.raises(RecurrenceError) as info:
        build_rule(**kwargs)
    assert (info.value.code, info.value.field) == (code, field)


# --- API ------------------------------------------------------------------------------------


def body(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": "Сводка новостей",
        "description": "Собери главные новости за ночь.",
        "recurrence": {"kind": "daily", "time": "08:00"},
        "timezone": ALMATY,
    }
    payload.update(overrides)
    return payload


async def create(client: httpx.AsyncClient, **overrides: Any) -> httpx.Response:
    return await client.post(
        "/api/v1/schedules", json=body(**overrides), headers=await csrf_headers(client)
    )


async def test_crud_with_computed_next_run(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        resp = await create(client)
        assert resp.status_code == 201, resp.text
        created = resp.json()
        assert created["target"] == "orchestrator" and created["enabled"] is True
        assert created["recurrence"] == {
            "kind": "daily",
            "time": "08:00",
            "weekdays": [],
            "day_of_month": None,
            "interval_hours": None,
            "run_at": None,
        }
        nxt = datetime.fromisoformat(created["next_run_at"])
        assert nxt > datetime.now(UTC)
        assert local(nxt, ALMATY).strftime("%H:%M") == "08:00"

        listing = (await client.get("/api/v1/schedules")).json()
        assert [s["id"] for s in listing["items"]] == [created["id"]]
        assert listing["max_schedules"] == 50 and listing["min_interval_minutes"] == 60

        sid = created["id"]
        resp = await client.patch(
            f"/api/v1/schedules/{sid}",
            json={"recurrence": {"kind": "weekly", "time": "09:00", "weekdays": [1]}},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 200, resp.text
        weekly = resp.json()
        moment = local(datetime.fromisoformat(weekly["next_run_at"]), ALMATY)
        assert (moment.isoweekday(), moment.strftime("%H:%M")) == (1, "09:00")

        resp = await client.patch(
            f"/api/v1/schedules/{sid}", json={"enabled": False}, headers=await csrf_headers(client)
        )
        assert resp.json()["enabled"] is False and resp.json()["next_run_at"] is None
        resp = await client.patch(
            f"/api/v1/schedules/{sid}", json={"enabled": True}, headers=await csrf_headers(client)
        )
        assert resp.json()["next_run_at"] == weekly["next_run_at"]

        resp = await client.delete(f"/api/v1/schedules/{sid}", headers=await csrf_headers(client))
        assert resp.status_code == 204
        assert (await client.get(f"/api/v1/schedules/{sid}")).status_code == 404

    async with app.state.db.sessionmaker() as db:
        actions = list(
            (
                await db.execute(
                    select(AuditLog.action).where(AuditLog.resource_type == "schedule")
                )
            ).scalars()
        )
        types = list(
            (
                await db.execute(
                    select(AgentEvent.type)
                    .where(AgentEvent.type.like("schedule.%"))
                    .order_by(AgentEvent.seq)
                )
            ).scalars()
        )
    assert actions.count("schedule.updated") == 3
    assert {"schedule.created", "schedule.deleted"} <= set(actions)
    assert types[0] == "schedule.created" and types[-1] == "schedule.deleted"


async def test_validation_errors_have_codes(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        resp = await create(client, timezone="Nowhere/City")
        assert (resp.status_code, resp.json()["error"]["code"]) == (422, "invalid_timezone")
        resp = await create(client, recurrence={"kind": "weekly", "time": "08:00"})
        assert resp.json()["error"]["code"] == "invalid_recurrence"
        assert resp.json()["error"]["details"] == {"field": "weekdays"}
        resp = await create(client, recurrence={"kind": "hourly", "interval_hours": 7})
        assert resp.json()["error"]["code"] == "invalid_recurrence"
        resp = await create(client, recurrence={"kind": "once", "run_at": "2020-01-01T08:00:00"})
        assert (resp.status_code, resp.json()["error"]["code"]) == (422, "schedule_in_past")
        resp = await create(client, recurrence={"kind": "daily", "time": "25:00"})
        assert resp.json()["error"]["code"] == "validation_error"
        resp = await create(client, target="agent")
        assert resp.json()["error"]["code"] == "invalid_schedule_target"
        await add_mock_model(client)
        resp = await create(client, target="agent", agent_id=str(uuid.uuid4()))
        assert resp.status_code == 404
        agent = await create_agent(client)
        await client.delete(f"/api/v1/agents/{agent['id']}", headers=await csrf_headers(client))
        resp = await create(client, target="agent", agent_id=agent["id"])
        assert (resp.status_code, resp.json()["error"]["code"]) == (409, "agent_archived")


async def test_limits_are_settings(app_factory: Any) -> None:
    app = await app_factory(schedules_max_per_user=1, schedule_min_interval_minutes=120)
    async with app.state.db.sessionmaker() as session:
        from app.services.users import UserService
        from tests.conftest import OWNER_PASSWORD, OWNER_USERNAME

        await UserService(session).create_owner(OWNER_USERNAME, OWNER_PASSWORD, "Owner")
    async with logged_in_client(app) as client:
        resp = await create(client, recurrence={"kind": "hourly", "interval_hours": 1})
        assert (resp.status_code, resp.json()["error"]["code"]) == (422, "interval_too_short")
        resp = await create(client, recurrence={"kind": "hourly", "interval_hours": 2})
        assert resp.status_code == 201
        resp = await create(client)
        assert (resp.status_code, resp.json()["error"]["code"]) == (409, "too_many_schedules")


async def test_preview_lists_the_next_runs(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        resp = await client.post(
            "/api/v1/schedules/preview",
            json={
                "recurrence": {"kind": "weekly", "time": "08:00", "weekdays": [1, 2, 3, 4, 5]},
                "timezone": ALMATY,
            },
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 200, resp.text
        runs = [local(datetime.fromisoformat(r), ALMATY) for r in resp.json()["next_runs"]]
        assert len(runs) == 3
        assert all(r.isoweekday() <= 5 and r.strftime("%H:%M") == "08:00" for r in runs)
        resp = await client.post(
            "/api/v1/schedules/preview",
            json={"recurrence": {"kind": "once", "run_at": "2020-01-01T08:00"}, "timezone": ALMATY},
            headers=await csrf_headers(client),
        )
        assert resp.json()["error"]["code"] == "schedule_in_past"


async def test_run_now_starts_a_task_through_the_orchestrator(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        sid = (await create(client)).json()["id"]
        planned = (await client.get(f"/api/v1/schedules/{sid}")).json()["next_run_at"]
        resp = await client.post(
            f"/api/v1/schedules/{sid}/run-now", headers=await csrf_headers(client)
        )
        assert resp.status_code == 200, resp.text
        started = resp.json()
        task = started["task"]
        assert task["status"] == "queued" and task["created_by"] == "schedule"
        assert task["extra"] == {"schedule_id": sid}
        assert task["title"] == "Сводка новостей"
        assert started["schedule"]["last_task_id"] == task["id"]
        assert started["schedule"]["last_outcome"] == "started"
        assert started["schedule"]["next_run_at"] == planned  # the plan stays
        assert queue.enqueued == [uuid.UUID(task["id"])]
        # the Orchestrator now has that task: a second start is refused like a manual one
        resp = await client.post(
            f"/api/v1/schedules/{sid}/run-now", headers=await csrf_headers(client)
        )
        assert (resp.status_code, resp.json()["error"]["code"]) == (409, "agent_busy")
        listed = (await client.get("/api/v1/schedules")).json()["items"][0]
        assert listed["last_task_status"] == "queued"
        runs = (await client.get("/api/v1/runs")).json()
        assert [r["task_id"] for r in runs] == [task["id"]]  # visible in the Subagent Office


# --- the worker -----------------------------------------------------------------------------


async def due_pass(app: FastAPI, queue: RecordingQueue, now: datetime) -> int:
    return await run_due(app.state.db.sessionmaker, queue, app.state.settings, now=now)


async def load(app: FastAPI, sid: str) -> Schedule:
    async with app.state.db.sessionmaker() as db:
        s = await db.get(Schedule, uuid.UUID(sid))
        assert s is not None
        return s


async def tasks_of(app: FastAPI, sid: str) -> list[Task]:
    async with app.state.db.sessionmaker() as db:
        rows = await db.execute(
            select(Task).where(Task.extra["schedule_id"].astext == sid).order_by(Task.created_at)
        )
        return list(rows.scalars())


async def test_due_schedule_starts_once_and_plans_the_next(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        agent = await create_agent(client)
        sid = (await create(client, target="agent", agent_id=agent["id"])).json()["id"]
    due = (await load(app, sid)).next_run_at
    assert due is not None
    assert await due_pass(app, queue, due - timedelta(seconds=1)) == 0  # not yet
    now = due + timedelta(seconds=2)
    assert await due_pass(app, queue, now) == 1
    assert await due_pass(app, queue, now) == 0  # the same occurrence never starts twice
    s = await load(app, sid)
    tasks = await tasks_of(app, sid)
    assert len(tasks) == 1 and tasks[0].agent_id == uuid.UUID(agent["id"])
    assert queue.enqueued == [tasks[0].id]
    assert (s.last_task_id, s.last_outcome, s.last_run_at) == (tasks[0].id, "started", now)
    assert s.next_run_at == due + timedelta(days=1)


async def test_catch_up_runs_once_not_for_every_missed_day(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        sid = (await create(client)).json()["id"]
    due = (await load(app, sid)).next_run_at
    assert due is not None
    back = due + timedelta(days=3, hours=5)  # the server was down for three mornings
    assert await due_pass(app, queue, back) == 1
    assert len(await tasks_of(app, sid)) == 1
    s = await load(app, sid)
    assert s.next_run_at is not None and s.next_run_at > back
    assert s.next_run_at == due + timedelta(days=4)


async def test_disabled_schedule_is_not_started(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        sid = (await create(client, enabled=False)).json()["id"]
        other = (await create(client)).json()
        await client.patch(
            f"/api/v1/schedules/{other['id']}",
            json={"enabled": False},
            headers=await csrf_headers(client),
        )
    async with app.state.db.sessionmaker() as db:
        # even with a stale planned time left in the row
        await db.execute(
            text("UPDATE schedules SET next_run_at = now() - interval '1 hour' WHERE id = :id"),
            {"id": sid},
        )
        await db.commit()
    assert await due_pass(app, queue, datetime.now(UTC) + timedelta(days=2)) == 0
    assert await tasks_of(app, sid) == [] and await tasks_of(app, other["id"]) == []


async def test_busy_agent_waits_then_the_run_is_skipped(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        agent = await create_agent(client)
        sid = (await create(client, target="agent", agent_id=agent["id"])).json()["id"]
        assert (await run_agent(client, agent["id"], "Something long")).status_code == 200
    due = (await load(app, sid)).next_run_at
    assert due is not None
    now = due + timedelta(seconds=1)
    assert await due_pass(app, queue, now) == 0
    s = await load(app, sid)
    assert s.busy_since == now and s.next_run_at == now + timedelta(seconds=30)
    assert s.last_outcome is None
    # still busy past the wait (SCHEDULE_BUSY_WAIT_MINUTES=30): this occurrence is skipped
    later = now + timedelta(minutes=31)
    assert await due_pass(app, queue, later) == 0
    s = await load(app, sid)
    assert (s.last_outcome, s.last_reason, s.busy_since) == ("skipped", "agent_busy", None)
    assert s.enabled is True and s.next_run_at == due + timedelta(days=1)
    assert await tasks_of(app, sid) == []


async def test_busy_agent_that_frees_up_in_time_gets_the_run(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        agent = await create_agent(client)
        sid = (await create(client, target="agent", agent_id=agent["id"])).json()["id"]
        busy = (await run_agent(client, agent["id"], "Short job")).json()["task"]["id"]
        due = (await load(app, sid)).next_run_at
        assert due is not None
        assert await due_pass(app, queue, due + timedelta(seconds=1)) == 0
        resp = await client.post(f"/api/v1/tasks/{busy}/cancel", headers=await csrf_headers(client))
        assert resp.status_code == 200, resp.text
    assert await due_pass(app, queue, due + timedelta(minutes=1)) == 1
    s = await load(app, sid)
    assert (s.last_outcome, s.busy_since) == ("started", None)
    assert s.next_run_at == due + timedelta(days=1)


async def test_no_wait_setting_skips_a_busy_run_at_once(app_factory: Any) -> None:
    app = await app_factory(schedule_busy_wait_minutes=0)
    queue = RecordingQueue()
    app.state.queue = queue
    async with app.state.db.sessionmaker() as session:
        from app.services.users import UserService
        from tests.conftest import OWNER_PASSWORD, OWNER_USERNAME

        await UserService(session).create_owner(OWNER_USERNAME, OWNER_PASSWORD, "Owner")
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        agent = await create_agent(client)
        sid = (await create(client, target="agent", agent_id=agent["id"])).json()["id"]
        await run_agent(client, agent["id"], "Busy")
    due = (await load(app, sid)).next_run_at
    assert due is not None
    await due_pass(app, queue, due + timedelta(seconds=1))
    s = await load(app, sid)
    assert (s.last_outcome, s.last_reason) == ("skipped", "agent_busy")


async def test_kill_switch_skips_and_deleted_agent_switches_off(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        agent = await create_agent(client)
        orch = (await create(client)).json()["id"]
        own = (await create(client, target="agent", agent_id=agent["id"])).json()["id"]
        await client.post("/api/v1/system/stop-all", headers=await csrf_headers(client))
        due = (await load(app, orch)).next_run_at
        assert due is not None
        assert await due_pass(app, queue, due + timedelta(seconds=1)) == 0
        for sid in (orch, own):
            s = await load(app, sid)
            assert (s.last_outcome, s.last_reason, s.enabled) == ("skipped", "engine_stopped", True)
            assert s.next_run_at == due + timedelta(days=1)
        await client.post("/api/v1/system/start", headers=await csrf_headers(client))
        await client.delete(f"/api/v1/agents/{agent['id']}", headers=await csrf_headers(client))
    assert await due_pass(app, queue, due + timedelta(days=1, seconds=1)) == 1  # the Orchestrator
    s = await load(app, own)
    assert (s.last_reason, s.enabled, s.next_run_at) == ("agent_archived", False, None)
    async with app.state.db.sessionmaker() as db:
        skipped = (
            await db.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "schedule.skipped")
            )
        ).scalar_one()
    assert skipped == 3


async def test_one_off_runs_once_and_switches_off(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    at = (datetime.now(ZoneInfo(ALMATY)) + timedelta(hours=1)).replace(tzinfo=None, microsecond=0)
    async with logged_in_client(app) as client:
        resp = await create(client, recurrence={"kind": "once", "run_at": at.isoformat()})
        assert resp.status_code == 201, resp.text
        sid = resp.json()["id"]
        assert (
            local(datetime.fromisoformat(resp.json()["next_run_at"]), ALMATY).replace(tzinfo=None)
            == at
        )
    due = (await load(app, sid)).next_run_at
    assert due is not None
    assert await due_pass(app, queue, due + timedelta(seconds=5)) == 1
    s = await load(app, sid)
    assert (s.enabled, s.next_run_at, s.last_outcome) == (False, None, "started")
    async with logged_in_client(app) as client:
        # Switched back on while its moment is still ahead (real clock): planned again.
        resp = await client.patch(
            f"/api/v1/schedules/{sid}", json={"enabled": True}, headers=await csrf_headers(client)
        )
        assert resp.status_code == 200
        assert datetime.fromisoformat(resp.json()["next_run_at"]) == due


async def test_saving_the_same_rule_keeps_a_waiting_run(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        agent = await create_agent(client)
        sid = (await create(client, target="agent", agent_id=agent["id"])).json()["id"]
        await run_agent(client, agent["id"], "Busy")
        due = (await load(app, sid)).next_run_at
        assert due is not None
        await due_pass(app, queue, due + timedelta(seconds=1))
        waiting = await load(app, sid)
        assert waiting.busy_since is not None
        # the form sends everything again; only the title is new
        resp = await client.patch(
            f"/api/v1/schedules/{sid}",
            json={**body(title="Другое"), "target": "agent", "agent_id": agent["id"]},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 200, resp.text
    s = await load(app, sid)
    assert s.title == "Другое"
    assert (s.busy_since, s.next_run_at) == (waiting.busy_since, waiting.next_run_at)
    async with app.state.db.sessionmaker() as db:
        last = (
            await db.execute(
                select(AgentEvent)
                .where(AgentEvent.type == "schedule.updated")
                .order_by(AgentEvent.seq.desc())
                .limit(1)
            )
        ).scalar_one()
    assert last.payload["changed"] == ["title"]


async def test_concurrent_workers_start_an_occurrence_once(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        ids = [(await create(client, title=f"S{i}")).json()["id"] for i in range(3)]
    due = (await load(app, ids[0])).next_run_at
    assert due is not None
    now = due + timedelta(seconds=1)
    results = await asyncio.gather(*(due_pass(app, queue, now) for _ in range(4)))
    # One Orchestrator: the first occurrence starts it, the other two wait for it (busy).
    assert sum(results) == 1
    assert sum([len(await tasks_of(app, sid)) for sid in ids]) == 1
    assert len(queue.enqueued) == 1


async def test_a_row_locked_elsewhere_is_skipped_not_waited_for(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        sid = (await create(client)).json()["id"]
    due = (await load(app, sid)).next_run_at
    assert due is not None
    async with app.state.db.sessionmaker() as other:
        await other.execute(text("SELECT id FROM schedules WHERE id = :id FOR UPDATE"), {"id": sid})
        assert await asyncio.wait_for(due_pass(app, queue, due + timedelta(seconds=1)), 5) == 0
        await other.rollback()
    assert await due_pass(app, queue, due + timedelta(seconds=1)) == 1


async def test_schedule_events_match_the_contract(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    schema = json.loads((SCHEMAS / "event-envelope.schema.json").read_text())
    async with logged_in_client(app) as client:
        sid = (await create(client)).json()["id"]
        await client.post(f"/api/v1/schedules/{sid}/run-now", headers=await csrf_headers(client))
        await client.patch(
            f"/api/v1/schedules/{sid}", json={"title": "Новое"}, headers=await csrf_headers(client)
        )
        await client.delete(f"/api/v1/schedules/{sid}", headers=await csrf_headers(client))
    async with app.state.db.sessionmaker() as db:
        events = list(
            (
                await db.execute(select(AgentEvent).where(AgentEvent.type.like("schedule.%")))
            ).scalars()
        )
    assert {e.type for e in events} == {
        "schedule.created",
        "schedule.fired",
        "schedule.updated",
        "schedule.deleted",
    }
    for event in events:
        data = json.loads(json.dumps(envelope(event), default=str))
        jsonschema.validate(data, schema)
        assert "task" not in data["payload"]  # the realtime store reads payload.task as a task
