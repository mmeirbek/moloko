"""Scheduled tasks (owner request): CRUD, "run now" and the worker's due-run pass.

A due schedule starts exactly like a manual start (``POST /runs`` for the Orchestrator,
``POST /agents/{id}/run`` for a persistent agent): a new top-level task + run through
``prepare_start``, with the same checks — kill switch, budget hard stop, archived or busy
agent. The task is marked ``created_by="schedule"`` and ``extra.schedule_id``.

One occurrence = one transaction with the schedule row locked (``FOR UPDATE SKIP LOCKED``):
the task is created and queued, and the next run computed, together. Two workers, a
double tick or a restart can therefore never start one occurrence twice, and a crash
before the commit leaves the schedule due, so the next tick starts it.

* Missed runs (the server was down): the next run is computed from *now*, so any number
  of missed runs collapse into one catch-up run.
* Busy agent: the run waits (re-checked every tick) up to ``SCHEDULE_BUSY_WAIT_MINUTES``,
  then that occurrence is skipped with reason ``agent_busy``.
* Kill switch / budget used up: the occurrence is skipped (``engine_stopped`` /
  ``budget_exceeded``); the schedule stays on.
* The agent was deleted: the schedule is switched off (``agent_archived``).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.engine import agent_is_busy, lock_agent, task_payload
from app.agents.state import AgentType, TaskStatus, TaskType
from app.core.config import Settings
from app.core.errors import AppError, Conflict, NotFound
from app.events import bus
from app.models.agent import Agent, AgentRun
from app.models.schedule import Schedule
from app.models.task import Task
from app.orchestrator.service import ensure_orchestrator
from app.schedules.recurrence import (
    RecurrenceError,
    Rule,
    build_rule,
    format_time,
    next_after,
    upcoming,
)
from app.schemas.schedules import (
    RecurrenceIn,
    RecurrenceOut,
    ScheduleCreate,
    ScheduleOut,
    SchedulePreviewIn,
    ScheduleUpdate,
)
from app.services.audit import AuditService
from app.services.system import ensure_engine_running
from app.services.tasks import AgentArchived, AgentBusy, prepare_start
from app.services.usage import ensure_within_budget
from app.tasks.queue import TaskEnqueuer

logger = logging.getLogger("moloko.schedules")

Trigger = Literal["schedule", "run_now"]
PREVIEW_RUNS = 3


# --- errors -------------------------------------------------------------------------------


class InvalidRecurrence(AppError):
    status_code = 422
    code = "invalid_recurrence"
    message = "The schedule's repeat settings are incomplete or invalid."


class InvalidTimezone(AppError):
    status_code = 422
    code = "invalid_timezone"
    message = "Unknown time zone."


class IntervalTooShort(AppError):
    status_code = 422
    code = "interval_too_short"
    message = "This schedule repeats more often than the server allows."


class ScheduleInPast(AppError):
    status_code = 422
    code = "schedule_in_past"
    message = "This moment has already passed."


class InvalidScheduleTarget(AppError):
    status_code = 422
    code = "invalid_schedule_target"
    message = "Choose the Orchestrator or one of your persistent agents."


class TooManySchedules(Conflict):
    code = "too_many_schedules"
    message = "The maximum number of schedules is reached. Delete one first."


_RULE_ERRORS: dict[str, type[AppError]] = {
    "invalid_recurrence": InvalidRecurrence,
    "invalid_timezone": InvalidTimezone,
    "interval_too_short": IntervalTooShort,
}


class _NoOrchestrator(Exception):
    """The owner has no Orchestrator yet: create it outside the schedule's transaction."""


def _rule_error(exc: RecurrenceError) -> AppError:
    return _RULE_ERRORS.get(exc.code, InvalidRecurrence)(details={"field": exc.field})


# --- conversions -------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def stored_rule(s: Schedule) -> Rule:
    """The rule saved on a schedule (validated when it was saved; the interval floor may
    have been raised since — a saved schedule keeps working)."""
    return build_rule(
        kind=s.kind,
        timezone=s.timezone,
        time_of_day=s.at_time,
        weekdays=list(s.weekdays or []),
        day_of_month=s.day_of_month,
        interval_hours=s.interval_hours,
        run_at=s.run_at,
        min_interval_minutes=0,
    )


def _apply_rule(s: Schedule, rule: Rule) -> None:
    s.kind = rule.kind
    s.timezone = rule.timezone
    s.at_time = format_time(rule.time) if rule.time is not None else None
    s.weekdays = list(rule.weekdays) if rule.kind == "weekly" else []
    s.day_of_month = rule.day_of_month
    s.interval_hours = rule.interval_hours
    s.run_at = rule.run_at


def _rule_fields(s: Schedule) -> tuple[Any, ...]:
    return (
        s.kind,
        s.timezone,
        s.at_time,
        list(s.weekdays or []),
        s.day_of_month,
        s.interval_hours,
        s.run_at,
    )


def recurrence_out(s: Schedule) -> RecurrenceOut:
    return RecurrenceOut.model_validate(
        {
            "kind": s.kind,
            "time": s.at_time,
            "weekdays": list(s.weekdays or []),
            "day_of_month": s.day_of_month,
            "interval_hours": s.interval_hours,
            "run_at": s.run_at,
        }
    )


def schedule_out(s: Schedule, last_task_status: str | None) -> ScheduleOut:
    return ScheduleOut.model_validate(
        {
            "id": s.id,
            "title": s.title,
            "description": s.description,
            "target": s.target,
            "agent_id": s.agent_id,
            "recurrence": recurrence_out(s),
            "timezone": s.timezone,
            "enabled": s.enabled,
            "next_run_at": s.next_run_at,
            "busy_since": s.busy_since,
            "last_run_at": s.last_run_at,
            "last_task_id": s.last_task_id,
            "last_task_status": last_task_status,
            "last_outcome": s.last_outcome,
            "last_reason": s.last_reason,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
        }
    )


def _event_payload(s: Schedule, **extra: Any) -> dict[str, Any]:
    """Small on purpose (no task text): clients refetch the list on ``schedule.*``."""
    return {
        "schedule_id": str(s.id),
        "title": s.title,
        "enabled": s.enabled,
        "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
        **extra,
    }


async def _emit(
    db: AsyncSession,
    s: Schedule,
    type_: str,
    *,
    task_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    **extra: Any,
) -> None:
    await bus.emit(
        db,
        user_id=s.user_id,
        type=type_,
        task_id=task_id,
        run_id=run_id,
        agent_id=agent_id,
        payload=_event_payload(s, **extra),
    )


def _advance(s: Schedule, rule: Rule, now: datetime) -> None:
    """Plan the next run strictly after ``now``; a one-off that is done switches off."""
    s.busy_since = None
    s.next_run_at = next_after(rule, now) if s.enabled else None
    if s.next_run_at is None:
        s.enabled = False


# --- starting one occurrence ---------------------------------------------------------------


async def _target_agent(db: AsyncSession, s: Schedule) -> Agent:
    """The schedule's agent, row-locked."""
    if s.target == "orchestrator":
        agent_id = (
            await db.execute(
                select(Agent.id)
                .where(
                    Agent.user_id == s.user_id,
                    Agent.agent_type == AgentType.ORCHESTRATOR.value,
                    Agent.archived_at.is_(None),
                )
                .order_by(Agent.created_at)
                .limit(1)
            )
        ).scalar_one_or_none()
        if agent_id is None:
            raise _NoOrchestrator()
        return await lock_agent(db, agent_id)
    if s.agent_id is None:
        raise AgentArchived()
    agent = await lock_agent(db, s.agent_id)
    if agent.archived_at is not None:
        raise AgentArchived()
    return agent


async def check_start(db: AsyncSession, s: Schedule) -> Agent:
    """Everything a manual start checks, before anything is written (so a refusal can be
    recorded in the same transaction). Returns the target agent, locked."""
    await ensure_engine_running(db, s.user_id)
    await ensure_within_budget(db, s.user_id)
    agent = await _target_agent(db, s)
    if agent_is_busy(agent):
        raise AgentBusy()
    return agent


async def start_occurrence(
    db: AsyncSession,
    s: Schedule,
    agent: Agent,
    *,
    trigger: Trigger,
    now: datetime,
    actor_id: uuid.UUID | None = None,
) -> tuple[Task, AgentRun]:
    """Inside the caller's transaction (schedule and agent locked, ``check_start`` passed):
    a new task for the agent, queued. The caller plans the next run, commits, enqueues."""
    task = Task(
        user_id=s.user_id,
        title=s.title,
        description=s.description,
        task_type=TaskType.USER.value,
        status=TaskStatus.CREATED.value,
        priority=0,
        agent_id=agent.id,
        created_by="schedule",
        depends_on=[],
        extra={"schedule_id": str(s.id)},
    )
    db.add(task)
    await db.flush()
    await bus.emit(
        db,
        user_id=s.user_id,
        type="task.created",
        task_id=task.id,
        agent_id=agent.id,
        payload={"task": task_payload(task), "schedule_id": str(s.id)},
    )
    run = await prepare_start(db, task)
    s.last_run_at = now
    s.last_task_id = task.id
    s.last_outcome = "started"
    s.last_reason = None
    s.busy_since = None
    audit = AuditService(db)
    actor: Literal["user", "system"] = "user" if actor_id else "system"
    await audit.record(
        "agent.run_started",
        "success",
        actor_type=actor,
        actor_id=actor_id,
        user_id=s.user_id,
        resource_type="task",
        resource_id=str(task.id),
        details={"agent_id": str(agent.id), "run_id": str(run.id), "schedule_id": str(s.id)},
    )
    await audit.record(
        "schedule.fired",
        "success",
        actor_type=actor,
        actor_id=actor_id,
        user_id=s.user_id,
        resource_type="schedule",
        resource_id=str(s.id),
        details={"task_id": str(task.id), "trigger": trigger},
    )
    return task, run


async def _skip(
    db: AsyncSession, s: Schedule, rule: Rule | None, now: datetime, reason: str, *, off: bool
) -> None:
    """Record a refused occurrence and plan the next one (or switch off: ``off``)."""
    s.last_run_at = now
    s.last_outcome = "skipped" if reason != "start_failed" else "failed"
    s.last_reason = reason
    if off or rule is None:
        s.enabled = False
        s.next_run_at = None
        s.busy_since = None
    else:
        _advance(s, rule, now)
    await _emit(db, s, "schedule.skipped", reason=reason)
    await AuditService(db).record(
        "schedule.skipped",
        "failure",
        actor_type="system",
        user_id=s.user_id,
        resource_type="schedule",
        resource_id=str(s.id),
        details={"reason": reason, "switched_off": not s.enabled},
    )


# --- the worker's pass ---------------------------------------------------------------------

Outcome = Literal["started", "waiting", "skipped", "failed", "retry"]


async def _lock_due(db: AsyncSession, now: datetime) -> Schedule | None:
    return (
        await db.execute(
            select(Schedule)
            .where(Schedule.enabled.is_(True), Schedule.next_run_at <= now)
            .order_by(Schedule.next_run_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()


async def _handle_due(
    db: AsyncSession, s: Schedule, now: datetime, settings: Settings, queue: TaskEnqueuer | None
) -> Outcome:
    try:
        rule = stored_rule(s)
    except RecurrenceError as exc:  # e.g. a time zone the server no longer knows
        await _skip(db, s, None, now, exc.code, off=True)
        await bus.commit(db)
        return "skipped"
    try:
        agent = await check_start(db, s)
    except _NoOrchestrator:
        user_id = s.user_id
        await db.rollback()
        await ensure_orchestrator(db, user_id)
        return "retry"
    except AgentBusy:
        wait = timedelta(minutes=settings.schedule_busy_wait_minutes)
        if now - (s.busy_since or now) < wait:
            # Due again by the next tick (ticks are a minute apart, give or take).
            s.next_run_at = now + timedelta(seconds=30)
            if s.busy_since is None:
                s.busy_since = now
                await _emit(db, s, "schedule.updated", reason="waiting_for_agent")
            await bus.commit(db)
            return "waiting"
        await _skip(db, s, rule, now, AgentBusy.code, off=False)
        await bus.commit(db)
        return "skipped"
    except AgentArchived as exc:
        await _skip(db, s, rule, now, exc.code, off=True)
        await bus.commit(db)
        return "skipped"
    except AppError as exc:  # engine_stopped, budget_exceeded
        await _skip(db, s, rule, now, exc.code, off=False)
        await bus.commit(db)
        return "skipped"
    task, run = await start_occurrence(db, s, agent, trigger="schedule", now=now)
    _advance(s, rule, now)
    await _emit(
        db,
        s,
        "schedule.fired",
        task_id=task.id,
        run_id=run.id,
        agent_id=agent.id,
        trigger="schedule",
    )
    await bus.commit(db)
    if queue is not None:
        await queue.enqueue_task(task.id)
    return "started"


async def _record_failure(
    db: AsyncSession, schedule_id: uuid.UUID, due_at: datetime | None, now: datetime
) -> None:
    """After an unexpected error (rolled back): move on, so one broken schedule cannot
    block the others or retry every minute. Only if nobody handled it in the meantime."""
    s = (
        await db.execute(select(Schedule).where(Schedule.id == schedule_id).with_for_update())
    ).scalar_one_or_none()
    if s is None or not s.enabled or s.next_run_at != due_at:
        return
    try:
        rule: Rule | None = stored_rule(s)
    except RecurrenceError:
        rule = None
    await _skip(db, s, rule, now, "start_failed", off=False)
    await bus.commit(db)


async def run_due(
    sessionmaker: async_sessionmaker[AsyncSession],
    queue: TaskEnqueuer | None,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> int:
    """Start every schedule that is due (at most ``SCHEDULE_DUE_BATCH`` per call).
    Returns how many tasks were started."""
    now = now or _utcnow()
    started = 0
    for _ in range(settings.schedule_due_batch):
        async with sessionmaker() as db:
            s = await _lock_due(db, now)
            if s is None:
                break
            schedule_id, due_at = s.id, s.next_run_at
            try:
                outcome = await _handle_due(db, s, now, settings, queue)
            except Exception:
                logger.exception("schedule_start_failed", extra={"schedule_id": str(schedule_id)})
                await db.rollback()
                await _record_failure(db, schedule_id, due_at, now)
                continue
            if outcome == "started":
                started += 1
    return started


# --- owner-facing service ------------------------------------------------------------------


class ScheduleService:
    def __init__(
        self, db: AsyncSession, settings: Settings, queue: TaskEnqueuer | None = None
    ) -> None:
        self.db = db
        self.settings = settings
        self.queue = queue
        self.audit = AuditService(db)

    def _rule(self, recurrence: RecurrenceIn, timezone: str) -> Rule:
        try:
            return build_rule(
                kind=recurrence.kind,
                timezone=timezone,
                time_of_day=recurrence.time,
                weekdays=recurrence.weekdays,
                day_of_month=recurrence.day_of_month,
                interval_hours=recurrence.interval_hours,
                run_at=recurrence.run_at,
                min_interval_minutes=self.settings.schedule_min_interval_minutes,
            )
        except RecurrenceError as exc:
            raise _rule_error(exc) from None

    async def _task_status(self, task_id: uuid.UUID | None) -> str | None:
        if task_id is None:
            return None
        return (
            await self.db.execute(select(Task.status).where(Task.id == task_id))
        ).scalar_one_or_none()

    async def out(self, s: Schedule) -> ScheduleOut:
        return schedule_out(s, await self._task_status(s.last_task_id))

    async def list_schedules(self, user_id: uuid.UUID) -> list[ScheduleOut]:
        rows = list(
            (
                await self.db.execute(
                    select(Schedule)
                    .where(Schedule.user_id == user_id)
                    .order_by(Schedule.created_at, Schedule.id)
                )
            ).scalars()
        )
        task_ids = {s.last_task_id for s in rows if s.last_task_id}
        statuses: dict[uuid.UUID, str] = {}
        if task_ids:
            result = await self.db.execute(
                select(Task.id, Task.status).where(Task.id.in_(task_ids))
            )
            statuses = {row.id: row.status for row in result}
        return [
            schedule_out(s, statuses.get(s.last_task_id) if s.last_task_id else None) for s in rows
        ]

    async def get(self, user_id: uuid.UUID, schedule_id: uuid.UUID) -> Schedule:
        s = await self.db.get(Schedule, schedule_id)
        if s is None or s.user_id != user_id:
            raise NotFound("Schedule not found.")
        return s

    async def _lock(self, user_id: uuid.UUID, schedule_id: uuid.UUID) -> Schedule:
        s = (
            await self.db.execute(
                select(Schedule).where(Schedule.id == schedule_id).with_for_update()
            )
        ).scalar_one_or_none()
        if s is None or s.user_id != user_id:
            raise NotFound("Schedule not found.")
        return s

    async def _target(
        self, user_id: uuid.UUID, target: str, agent_id: uuid.UUID | None
    ) -> uuid.UUID | None:
        if target == "orchestrator":
            return None
        if agent_id is None:
            raise InvalidScheduleTarget(details={"field": "agent_id"})
        agent = await self.db.get(Agent, agent_id)
        if agent is None or agent.user_id != user_id:
            raise NotFound("Agent not found.")
        if agent.archived_at is not None:
            raise AgentArchived()
        if agent.agent_type != AgentType.AUTONOMOUS.value:
            raise InvalidScheduleTarget(details={"field": "agent_id"})
        return agent.id

    def _plan(self, s: Schedule, rule: Rule, now: datetime) -> None:
        s.busy_since = None
        if not s.enabled:
            s.next_run_at = None
            return
        upcoming_run = next_after(rule, now)
        if upcoming_run is None:
            raise ScheduleInPast(details={"field": "run_at"})
        s.next_run_at = upcoming_run

    async def create(
        self, user_id: uuid.UUID, data: ScheduleCreate, *, now: datetime | None = None
    ) -> ScheduleOut:
        now = now or _utcnow()
        count = (
            await self.db.execute(
                select(func.count()).select_from(Schedule).where(Schedule.user_id == user_id)
            )
        ).scalar_one()
        if count >= self.settings.schedules_max_per_user:
            raise TooManySchedules(details={"max": self.settings.schedules_max_per_user})
        rule = self._rule(data.recurrence, data.timezone)
        if data.target == "orchestrator":
            await ensure_orchestrator(self.db, user_id)  # may commit: before any lock
        s = Schedule(
            user_id=user_id,
            title=data.title,
            description=data.description,
            target=data.target,
            agent_id=await self._target(user_id, data.target, data.agent_id),
            enabled=data.enabled,
            weekdays=[],
        )
        _apply_rule(s, rule)
        self._plan(s, rule, now)
        self.db.add(s)
        await self.db.flush()
        await _emit(self.db, s, "schedule.created")
        await self.audit.record(
            "schedule.created",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="schedule",
            resource_id=str(s.id),
            details={"title": s.title, "kind": s.kind, "target": s.target},
        )
        await bus.commit(self.db)
        return schedule_out(s, None)

    async def update(
        self,
        user_id: uuid.UUID,
        schedule_id: uuid.UUID,
        data: ScheduleUpdate,
        *,
        now: datetime | None = None,
    ) -> ScheduleOut:
        now = now or _utcnow()
        if data.target == "orchestrator":
            await ensure_orchestrator(self.db, user_id)  # may commit: before the lock
        s = await self._lock(user_id, schedule_id)
        fields = data.model_fields_set
        changed: list[str] = []
        if data.title is not None and data.title != s.title:
            s.title = data.title
            changed.append("title")
        if data.description is not None and data.description != s.description:
            s.description = data.description
            changed.append("description")
        if "target" in fields or "agent_id" in fields:
            target = data.target or s.target
            agent_id = data.agent_id if "agent_id" in fields else s.agent_id
            new_agent_id = await self._target(user_id, target, agent_id)
            if (target, new_agent_id) != (s.target, s.agent_id):
                s.target, s.agent_id = target, new_agent_id
                changed.append("target")
        replan = False
        if data.recurrence is not None or data.timezone is not None:
            recurrence = data.recurrence or RecurrenceIn.model_validate(
                recurrence_out(s).model_dump()
            )
            rule = self._rule(recurrence, data.timezone or s.timezone)
            before = _rule_fields(s)
            _apply_rule(s, rule)
            # The form sends the rule with every save: re-plan only when it really changed,
            # or a run waiting for a busy agent would be dropped by an unrelated edit.
            if _rule_fields(s) != before:
                changed.append("recurrence")
                replan = True
        else:
            try:
                rule = stored_rule(s)
            except RecurrenceError as exc:
                raise _rule_error(exc) from None
        if data.enabled is not None and data.enabled != s.enabled:
            s.enabled = data.enabled
            changed.append("enabled")
            replan = True
        if replan:
            self._plan(s, rule, now)
        if changed:
            s.updated_at = now
            await _emit(self.db, s, "schedule.updated", changed=changed)
            await self.audit.record(
                "schedule.updated",
                "success",
                actor_type="user",
                actor_id=user_id,
                user_id=user_id,
                resource_type="schedule",
                resource_id=str(s.id),
                details={"changed": changed, "enabled": s.enabled},
            )
        await bus.commit(self.db)
        return await self.out(s)

    async def delete(self, user_id: uuid.UUID, schedule_id: uuid.UUID) -> None:
        s = await self._lock(user_id, schedule_id)
        await self.db.delete(s)
        await bus.emit(
            self.db,
            user_id=user_id,
            type="schedule.deleted",
            payload={"schedule_id": str(s.id), "title": s.title},
        )
        await self.audit.record(
            "schedule.deleted",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="schedule",
            resource_id=str(s.id),
            details={"title": s.title},
        )
        await bus.commit(self.db)

    def preview(self, data: SchedulePreviewIn, *, now: datetime | None = None) -> list[datetime]:
        rule = self._rule(data.recurrence, data.timezone)
        runs = upcoming(rule, now or _utcnow(), PREVIEW_RUNS)
        if not runs:
            raise ScheduleInPast(details={"field": "run_at"})
        return runs

    async def run_now(
        self, user_id: uuid.UUID, schedule_id: uuid.UUID, *, now: datetime | None = None
    ) -> tuple[ScheduleOut, Task, AgentRun]:
        """Start it now, outside the plan (``next_run_at`` stays as it is). Refusals are the
        same errors as a manual start (409 agent_busy, engine_stopped, budget_exceeded…)."""
        now = now or _utcnow()
        s = await self.get(user_id, schedule_id)
        if s.target == "orchestrator":
            await ensure_orchestrator(self.db, user_id)
        # Rows loaded so far may be stale: the locking reads below must refresh them, or the
        # busy check could see an agent as it was before another start committed.
        self.db.expire_all()
        s = await self._lock(user_id, schedule_id)
        try:
            agent = await check_start(self.db, s)
        except _NoOrchestrator:  # pragma: no cover — created just above
            raise NotFound("Agent not found.") from None
        task, run = await start_occurrence(
            self.db, s, agent, trigger="run_now", now=now, actor_id=user_id
        )
        await _emit(
            self.db,
            s,
            "schedule.fired",
            task_id=task.id,
            run_id=run.id,
            agent_id=agent.id,
            trigger="run_now",
        )
        await bus.commit(self.db)
        if self.queue is not None:
            await self.queue.enqueue_task(task.id)
        return schedule_out(s, task.status), task, run
