"""Tasks wait in line for their agent (owner's decision 2026-11-03: «очередь задач, чтобы
оркестратор мог делать сразу несколько задач»).

A task started for a busy agent is not refused: it stays ``created`` with the reason
``waiting_for_agent`` and starts by itself when the agent is free — oldest first (higher
priority first), one per agent per pass. The Orchestrator is free while the agents do the
parts of its plans (``orchestrator/runtime.py``), so it takes the next task meanwhile — up to
``ORCHESTRATOR_MAX_TASKS_AT_ONCE`` plans at a time; a plan whose parts are all done waits
here (``parts_done``) until the Orchestrator can merge them, before any new task.

Passes run after every run step (executor hook), every 30 s (worker sweep) and after a
cancel / stop (API). Parts of a plan wait for busy agents in ``orchestrator/scheduler.py``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.engine import (
    agent_is_busy,
    agent_payload,
    lock_agent,
    lock_task,
    set_task_reason,
    set_task_status,
)
from app.agents.state import AgentType, TaskStatus
from app.core.config import Settings
from app.events import bus
from app.models.agent import Agent
from app.models.chat import Message
from app.models.task import Task
from app.tasks.queue import TaskEnqueuer

logger = logging.getLogger("moloko.waiting")

# ORCHESTRATOR_MAX_TASKS_AT_ONCE, set once at startup (API and worker, like the event
# publisher) so every start — wherever it comes from — uses the same limit.
_max_plans: int = int(Settings.model_fields["orchestrator_max_tasks_at_once"].default)


def configure(settings: Settings) -> None:
    global _max_plans
    _max_plans = settings.orchestrator_max_tasks_at_once


def max_plans() -> int:
    return _max_plans


WAITING_FOR_AGENT = "waiting_for_agent"
# A plan whose parts are all done, waiting for its Orchestrator to merge them.
PARTS_DONE = "parts_done"
# The Orchestrator's plans that count toward ORCHESTRATOR_MAX_TASKS_AT_ONCE.
IN_FLIGHT = (
    TaskStatus.QUEUED.value,
    TaskStatus.RUNNING.value,
    TaskStatus.WAITING.value,
    TaskStatus.WAITING_APPROVAL.value,
)


async def plans_in_flight(db: AsyncSession, orchestrator: Agent, *, besides: uuid.UUID) -> int:
    rows = await db.execute(
        select(func.count())
        .select_from(Task)
        .where(
            Task.agent_id == orchestrator.id,
            Task.parent_task_id.is_(None),
            Task.status.in_(IN_FLIGHT),
            Task.id != besides,
        )
    )
    return int(rows.scalar_one())


async def has_room(db: AsyncSession, agent: Agent, task: Task) -> bool:
    """The agent can take ``task`` now: not busy, and an Orchestrator below its plan limit."""
    if agent_is_busy(agent):
        return False
    if agent.agent_type == AgentType.ORCHESTRATOR.value:
        return await plans_in_flight(db, agent, besides=task.id) < _max_plans
    return True


async def put_in_line(db: AsyncSession, task: Task) -> None:
    """A ``created`` task (row locked) waits for its agent; the clients show «в очереди»."""
    task.extra = {**(task.extra or {}), "in_line_since": datetime.now(UTC).isoformat()}
    await set_task_reason(db, task, WAITING_FOR_AGENT)


async def resume_merge(db: AsyncSession, task: Task, orchestrator: Agent) -> None:
    """All parts of the plan are done and its Orchestrator (row locked) is free: reserve it
    and queue the same run again (it merges the results)."""
    orchestrator.current_task_id = task.id
    orchestrator.run_id = task.run_id
    await bus.emit(
        db,
        user_id=orchestrator.user_id,
        type="agent.updated",
        agent_id=orchestrator.id,
        task_id=task.id,
        run_id=task.run_id,
        payload={"changed": ["current_task_id"], "agent": agent_payload(orchestrator)},
    )
    await set_task_status(db, task, TaskStatus.QUEUED, reason="subtasks_done")


async def wait_to_merge(db: AsyncSession, task: Task) -> None:
    """All parts are done but the Orchestrator is busy: the plan waits for it here."""
    await set_task_reason(db, task, PARTS_DONE)


def _in_line(user_id: uuid.UUID | None) -> Any:
    query = (
        select(Task.id, Task.agent_id, Task.user_id, Task.status)
        .where(
            Task.agent_id.is_not(None),
            ((Task.status == TaskStatus.CREATED.value) & (Task.status_reason == WAITING_FOR_AGENT))
            | ((Task.status == TaskStatus.WAITING.value) & (Task.status_reason == PARTS_DONE)),
        )
        # merging a finished plan first, then by priority, then the oldest
        .order_by(
            (Task.status == TaskStatus.WAITING.value).desc(),
            Task.priority.desc(),
            Task.created_at,
            Task.id,
        )
    )
    return query if user_id is None else query.where(Task.user_id == user_id)


async def dispatch(
    sessionmaker: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID | None = None,
) -> list[uuid.UUID]:
    """Start what waits for agents that are free now. Returns the tasks to enqueue."""
    from app.services.system import engine_stopped
    from app.services.tasks import TaskService, prepare_start

    async with sessionmaker() as db:
        rows = (await db.execute(_in_line(user_id))).all()
    started: list[uuid.UUID] = []
    tried: set[uuid.UUID] = set()
    for task_id, agent_id, owner_id, _ in rows:
        if agent_id in tried:
            continue
        tried.add(agent_id)
        async with sessionmaker() as db:
            if await engine_stopped(db, owner_id):
                continue  # the kill switch: nothing new starts
            task = await lock_task(db, task_id)
            agent = await lock_agent(db, agent_id)
            if task.status == TaskStatus.WAITING.value and task.status_reason == PARTS_DONE:
                if agent_is_busy(agent):
                    continue
                await resume_merge(db, task, agent)
            elif (
                task.status == TaskStatus.CREATED.value and task.status_reason == WAITING_FOR_AGENT
            ):
                if agent.archived_at is not None:
                    await TaskService(db, None)._cancel_tree(task, "agent_unavailable")
                    await bus.commit(db)
                    tried.discard(agent_id)
                    continue
                if not await has_room(db, agent, task):
                    continue
                conversation = (task.extra or {}).get("conversation_id")
                run = await prepare_start(
                    db, task, conversation_id=uuid.UUID(conversation) if conversation else None
                )
                # A hand-off from the chat: the owner's message links to the agents' run now.
                message_id = (task.extra or {}).get("chat_message_id")
                if message_id:
                    await db.execute(
                        update(Message)
                        .where(Message.id == uuid.UUID(str(message_id)))
                        .values(agent_run_id=run.id)
                    )
            else:
                continue
            await bus.commit(db)
            started.append(task.id)
    if started:
        logger.info("started_from_line", extra={"count": len(started)})
    return started


async def advance(
    sessionmaker: async_sessionmaker[AsyncSession],
    queue: TaskEnqueuer | None,
    user_id: uuid.UUID | None = None,
) -> int:
    started = await dispatch(sessionmaker, user_id)
    if queue is not None:
        for task_id in started:
            await queue.enqueue_task(task_id)
    return len(started)


async def after_task(
    sessionmaker: async_sessionmaker[AsyncSession],
    task_id: uuid.UUID,
    queue: TaskEnqueuer | None,
) -> None:
    """Executor hook: a run step ended — its agent may be free for the next task in line."""
    async with sessionmaker() as db:
        user_id = (
            await db.execute(select(Task.user_id).where(Task.id == task_id))
        ).scalar_one_or_none()
    if user_id is not None:
        await advance(sessionmaker, queue, user_id)


async def after_change(db: AsyncSession, queue: TaskEnqueuer | None, user_id: uuid.UUID) -> None:
    """API hook after a cancel / stop (already committed): the next task starts now, not at
    the next sweep. Uses fresh sessions."""
    sessionmaker = async_sessionmaker(db.bind, expire_on_commit=False)
    try:
        await advance(sessionmaker, queue, user_id)
    except Exception:  # noqa: BLE001 — the worker's sweeper retries within seconds
        logger.warning("waiting_dispatch_failed", extra={"user_id": str(user_id)})
