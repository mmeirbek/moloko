"""Agent and task state machines (spec 8.4 / 8.5). Invalid transitions are rejected.

Additions where the spec is silent (see docs/decisions.md):
* agent ``<active> → idle`` = "stop" (task cancelled or engine stopped);
* agent ``failed → idle`` for persistent agents (the next run starts from idle);
* task ``running → queued`` (restart recovery: safe to resume) and
  ``waiting → queued`` (user resumed a paused / waiting task).
"""

from __future__ import annotations

from enum import StrEnum

from app.core.errors import AppError


class AgentStatus(StrEnum):
    IDLE = "idle"
    PLANNING = "planning"
    WORKING = "working"
    WAITING = "waiting"
    REVIEWING = "reviewing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentType(StrEnum):
    ORCHESTRATOR = "orchestrator"
    SUBAGENT = "subagent"
    AUTONOMOUS = "autonomous"


class AutonomyLevel(StrEnum):
    SUPERVISED = "supervised"
    BALANCED = "balanced"
    RESTRICTED = "restricted"


class MemoryType(StrEnum):
    """Spec 8.4 / 17."""

    USER = "user"  # facts about the owner, shared by all agents
    AGENT = "agent"  # one agent's own notes
    PROJECT = "project"  # notes about a named project
    TASK_CONTEXT = "task_context"
    CONVERSATION_CONTEXT = "conversation_context"


class TaskStatus(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(StrEnum):
    USER = "user"
    AGENT = "agent"
    SUBTASK = "subtask"
    REVIEW = "review"
    # "scheduled" is reserved by the spec for the future and deliberately not implemented.


ACTIVE_AGENT = frozenset(
    {AgentStatus.PLANNING, AgentStatus.WORKING, AgentStatus.WAITING, AgentStatus.REVIEWING}
)
TERMINAL_TASK = frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED})
ACTIVE_TASK = frozenset(set(TaskStatus) - TERMINAL_TASK)

_AGENT: dict[AgentStatus, frozenset[AgentStatus]] = {
    AgentStatus.IDLE: frozenset({AgentStatus.PLANNING, AgentStatus.WORKING}),
    AgentStatus.PLANNING: frozenset({AgentStatus.WORKING, AgentStatus.WAITING}),
    AgentStatus.WORKING: frozenset({AgentStatus.WAITING, AgentStatus.REVIEWING}),
    AgentStatus.WAITING: frozenset({AgentStatus.WORKING, AgentStatus.PLANNING}),
    AgentStatus.REVIEWING: frozenset({AgentStatus.COMPLETED, AgentStatus.WORKING}),
    AgentStatus.PAUSED: frozenset(),  # resume returns to the remembered state (see below)
    AgentStatus.COMPLETED: frozenset(),
    AgentStatus.FAILED: frozenset(),
}

_TASK: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.CREATED: frozenset({TaskStatus.QUEUED, TaskStatus.CANCELLED}),
    TaskStatus.QUEUED: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.WAITING_APPROVAL,
            TaskStatus.WAITING,
            TaskStatus.CANCELLED,
            TaskStatus.QUEUED,
        }
    ),
    TaskStatus.WAITING_APPROVAL: frozenset(
        {TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.QUEUED}
    ),
    TaskStatus.WAITING: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.QUEUED}),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset(),  # retry creates a NEW task (attempt + 1)
    TaskStatus.CANCELLED: frozenset(),
}


class InvalidTransition(AppError):
    status_code = 409
    code = "invalid_transition"
    message = "This action is not possible in the current state."


def agent_transition_allowed(
    current: AgentStatus,
    new: AgentStatus,
    *,
    agent_type: AgentType,
    paused_from: AgentStatus | None = None,
) -> bool:
    if current == new:
        return False
    persistent = agent_type != AgentType.SUBAGENT
    if new == AgentStatus.FAILED:
        return current != AgentStatus.FAILED and (persistent or current != AgentStatus.COMPLETED)
    if new == AgentStatus.PAUSED:
        return current in ACTIVE_AGENT
    if current == AgentStatus.PAUSED:
        # resume to the remembered active state, or stop
        return new == paused_from or new == AgentStatus.IDLE
    if new == AgentStatus.IDLE:
        if current in ACTIVE_AGENT:
            return True  # stop
        return persistent and current in (AgentStatus.COMPLETED, AgentStatus.FAILED)
    return new in _AGENT[current]


def check_agent_transition(
    current: AgentStatus,
    new: AgentStatus,
    *,
    agent_type: AgentType,
    paused_from: AgentStatus | None = None,
) -> None:
    if not agent_transition_allowed(current, new, agent_type=agent_type, paused_from=paused_from):
        raise InvalidTransition(
            f"An agent cannot go from '{current}' to '{new}'.",
            details={"from": str(current), "to": str(new)},
        )


def task_transition_allowed(current: TaskStatus, new: TaskStatus) -> bool:
    return new in _TASK[current]


def check_task_transition(current: TaskStatus, new: TaskStatus) -> None:
    if not task_transition_allowed(current, new):
        raise InvalidTransition(
            f"A task cannot go from '{current}' to '{new}'.",
            details={"from": str(current), "to": str(new)},
        )
