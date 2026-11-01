"""The only place that changes agent / task / run status.

Every change is validated against the state machines (app/agents/state.py) and writes
an event into the same transaction (spec invariant 4). Callers commit with
``app.events.bus.commit`` so events are published after the commit.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import (
    ACTIVE_AGENT,
    TERMINAL_TASK,
    AgentStatus,
    AgentType,
    TaskStatus,
    check_agent_transition,
    check_task_transition,
)
from app.core.errors import NotFound
from app.events.bus import emit
from app.models.agent import Agent, AgentRun
from app.models.task import Task
from app.schemas.agents import AgentOut
from app.schemas.tasks import RunOut, TaskOut


def utcnow() -> datetime:
    return datetime.now(UTC)


def agent_payload(agent: Agent) -> dict[str, Any]:
    return AgentOut.model_validate(agent).model_dump(mode="json")


def task_payload(task: Task) -> dict[str, Any]:
    return TaskOut.model_validate(task).model_dump(mode="json")


def run_payload(run: AgentRun) -> dict[str, Any]:
    return RunOut.model_validate(run).model_dump(mode="json")


# --- loading with row locks ---------------------------------------------------------


async def lock_task(db: AsyncSession, task_id: uuid.UUID) -> Task:
    task = (
        await db.execute(select(Task).where(Task.id == task_id).with_for_update())
    ).scalar_one_or_none()
    if task is None:
        raise NotFound("Task not found.")
    return task


async def lock_agent(db: AsyncSession, agent_id: uuid.UUID) -> Agent:
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id).with_for_update())
    ).scalar_one_or_none()
    if agent is None:
        raise NotFound("Agent not found.")
    return agent


async def lock_run(db: AsyncSession, run_id: uuid.UUID) -> AgentRun:
    run = (
        await db.execute(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
    ).scalar_one_or_none()
    if run is None:
        raise NotFound("Run not found.")
    return run


# --- transitions ----------------------------------------------------------------------


async def set_agent_status(
    db: AsyncSession, agent: Agent, new: AgentStatus, *, reason: str | None = None
) -> None:
    old = AgentStatus(agent.status)
    paused_from = AgentStatus(agent.paused_from) if agent.paused_from else None
    check_agent_transition(
        old, new, agent_type=AgentType(agent.agent_type), paused_from=paused_from
    )
    if new == AgentStatus.PAUSED:
        agent.paused_from = old.value
    elif old == AgentStatus.PAUSED:
        agent.paused_from = None
    agent.status = new.value
    agent.updated_at = utcnow()
    await emit(
        db,
        user_id=agent.user_id,
        type="agent.status_changed",
        agent_id=agent.id,
        task_id=agent.current_task_id,
        run_id=agent.run_id,
        payload={
            "old_status": old.value,
            "new_status": new.value,
            "reason": reason,
            "agent": agent_payload(agent),
        },
    )


async def release_agent(
    db: AsyncSession, agent: Agent, *, to: AgentStatus, reason: str | None = None
) -> None:
    """End the agent's current task and move it to ``to`` (idle / completed / failed)."""
    if AgentStatus(agent.status) != to:
        await set_agent_status(db, agent, to, reason=reason)
    if agent.agent_type != AgentType.SUBAGENT.value and to == AgentStatus.COMPLETED:
        # Persistent agents return to idle after a task (spec 8.5).
        agent.current_task_id = None
        await set_agent_status(db, agent, AgentStatus.IDLE, reason="task_finished")
    agent.current_task_id = None


_TASK_EVENT = {
    TaskStatus.COMPLETED: "task.completed",
    TaskStatus.FAILED: "task.failed",
    TaskStatus.CANCELLED: "task.cancelled",
}


async def set_task_status(
    db: AsyncSession,
    task: Task,
    new: TaskStatus,
    *,
    reason: str | None = None,
    result: str | None = None,
    error: tuple[str, str, str] | None = None,
    run: AgentRun | None = None,
) -> None:
    old = TaskStatus(task.status)
    check_task_transition(old, new)
    now = utcnow()
    task.status = new.value
    task.status_reason = reason
    task.updated_at = now
    if new == TaskStatus.RUNNING and task.started_at is None:
        task.started_at = now
    if new in TERMINAL_TASK:
        task.completed_at = now
        if new == TaskStatus.COMPLETED:
            task.progress = 100
    if result is not None:
        task.result = result
    if error is not None:
        task.error_code, task.error_message, task.error_id = error[0], error[1][:500], error[2]
    if run is not None:
        run.status = new.value
        if new == TaskStatus.RUNNING and run.started_at is None:
            run.started_at = now
        if new in TERMINAL_TASK:
            run.finished_at = now
            if result is not None:
                run.result = result
            if error is not None:
                run.error_code, run.error_message, run.error_id = error[0], error[1][:500], error[2]
    await emit(
        db,
        user_id=task.user_id,
        type=_TASK_EVENT.get(new, "task.updated"),
        agent_id=task.agent_id,
        task_id=task.id,
        run_id=task.run_id,
        payload={
            "old_status": old.value,
            "new_status": new.value,
            "reason": reason,
            "task": task_payload(task),
        },
    )


def agent_is_busy(agent: Agent) -> bool:
    return agent.current_task_id is not None or AgentStatus(agent.status) in ACTIVE_AGENT | {
        AgentStatus.PAUSED
    }
