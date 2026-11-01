"""Restart recovery (spec 9.1). Runs when the worker starts, before it takes jobs.

1. ``running`` tasks were interrupted. If the checkpoint shows no side-effecting
   operation in flight → back to ``queued`` (resume). Otherwise → ``waiting`` with
   reason ``unknown_outcome``: the user decides — we never auto-repeat an operation
   whose outcome is unknown.
2. ``queued`` tasks are (re-)enqueued.
3. ``waiting`` / ``waiting_approval`` tasks stay as they are.
4. Agents that look active without an active task are reset.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.engine import (
    lock_agent,
    lock_run,
    lock_task,
    release_agent,
    set_agent_status,
    set_task_status,
)
from app.agents.state import (
    ACTIVE_AGENT,
    ACTIVE_TASK,
    AgentStatus,
    AgentType,
    TaskStatus,
    agent_transition_allowed,
)
from app.events import bus
from app.models.agent import Agent
from app.models.task import Task
from app.tasks.queue import TaskEnqueuer

logger = logging.getLogger("moloko.recovery")


async def recover(
    sessionmaker: async_sessionmaker[AsyncSession], queue: TaskEnqueuer | None
) -> dict[str, int]:
    stats = {"resumed": 0, "needs_decision": 0, "enqueued": 0, "agents_reset": 0}
    async with sessionmaker() as db:
        running = list(
            (
                await db.execute(select(Task.id).where(Task.status == TaskStatus.RUNNING.value))
            ).scalars()
        )
    for task_id in running:
        async with sessionmaker() as db:
            task = await lock_task(db, task_id)
            if TaskStatus(task.status) != TaskStatus.RUNNING or task.run_id is None:
                continue
            run = await lock_run(db, task.run_id)
            in_flight = (run.state or {}).get("in_flight")
            if in_flight and in_flight.get("side_effects"):
                await set_task_status(
                    db, task, TaskStatus.WAITING, reason="unknown_outcome", run=run
                )
                await bus.emit(
                    db,
                    user_id=task.user_id,
                    type="task.updated",
                    task_id=task.id,
                    agent_id=task.agent_id,
                    run_id=run.id,
                    payload={
                        "reason": "unknown_outcome",
                        "operation": in_flight,
                        "needs_user_decision": True,
                    },
                )
                if task.agent_id:
                    agent = await lock_agent(db, task.agent_id)
                    if AgentStatus(agent.status) in (AgentStatus.WORKING, AgentStatus.PLANNING):
                        await set_agent_status(
                            db, agent, AgentStatus.WAITING, reason="unknown_outcome"
                        )
                stats["needs_decision"] += 1
            else:
                await set_task_status(
                    db, task, TaskStatus.QUEUED, reason="recovered_after_restart", run=run
                )
                stats["resumed"] += 1
            await bus.commit(db)

    async with sessionmaker() as db:
        queued = list(
            (
                await db.execute(select(Task.id).where(Task.status == TaskStatus.QUEUED.value))
            ).scalars()
        )
    if queue is not None:
        for task_id in queued:
            if await queue.enqueue_task(task_id):
                stats["enqueued"] += 1

    async with sessionmaker() as db:
        agents = list(
            (
                await db.execute(
                    select(Agent.id).where(
                        Agent.status.in_([s.value for s in ACTIVE_AGENT | {AgentStatus.PAUSED}])
                    )
                )
            ).scalars()
        )
    for agent_id in agents:
        async with sessionmaker() as db:
            agent = await lock_agent(db, agent_id)
            current = await db.get(Task, agent.current_task_id) if agent.current_task_id else None
            if current is not None and TaskStatus(current.status) in ACTIVE_TASK:
                continue
            target = (
                AgentStatus.IDLE
                if agent.agent_type != AgentType.SUBAGENT.value
                else AgentStatus.FAILED
            )
            paused_from = AgentStatus(agent.paused_from) if agent.paused_from else None
            if agent_transition_allowed(
                AgentStatus(agent.status),
                target,
                agent_type=AgentType(agent.agent_type),
                paused_from=paused_from,
            ):
                await release_agent(db, agent, to=target, reason="recovered_after_restart")
                await bus.commit(db)
                stats["agents_reset"] += 1
    logger.info("recovery_done", extra=stats)
    return stats


async def sweep_queued(
    sessionmaker: async_sessionmaker[AsyncSession], queue: TaskEnqueuer, older_than_seconds: int
) -> int:
    """Re-enqueue tasks that sit in ``queued`` too long (lost enqueue, Redis outage)."""
    cutoff = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
    async with sessionmaker() as db:
        stale = list(
            (
                await db.execute(
                    select(Task.id).where(
                        Task.status == TaskStatus.QUEUED.value, Task.updated_at < cutoff
                    )
                )
            ).scalars()
        )
    count = 0
    for task_id in stale:
        if await queue.enqueue_task(task_id):
            count += 1
    return count
