from __future__ import annotations

import pytest

from app.agents.state import (
    AgentStatus as A,
)
from app.agents.state import (
    AgentType,
    InvalidTransition,
    agent_transition_allowed,
    check_agent_transition,
    check_task_transition,
    task_transition_allowed,
)
from app.agents.state import (
    TaskStatus as T,
)

AUTO = AgentType.AUTONOMOUS
SUB = AgentType.SUBAGENT


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (A.IDLE, A.PLANNING),
        (A.PLANNING, A.WORKING),
        (A.WORKING, A.REVIEWING),
        (A.REVIEWING, A.COMPLETED),
        (A.WORKING, A.WAITING),
        (A.WAITING, A.WORKING),
        (A.WORKING, A.PAUSED),
        (A.WORKING, A.FAILED),
        (A.PLANNING, A.FAILED),
        (A.WORKING, A.IDLE),  # stop
    ],
)
def test_spec_agent_transitions_are_allowed(old: A, new: A) -> None:
    assert agent_transition_allowed(old, new, agent_type=AUTO)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (A.IDLE, A.COMPLETED),
        (A.IDLE, A.REVIEWING),
        (A.PLANNING, A.COMPLETED),
        (A.WORKING, A.COMPLETED),  # must review first
        (A.IDLE, A.PAUSED),  # only active agents pause
        (A.COMPLETED, A.WORKING),
        (A.FAILED, A.WORKING),
        (A.IDLE, A.IDLE),
    ],
)
def test_invalid_agent_transitions_are_rejected(old: A, new: A) -> None:
    assert not agent_transition_allowed(old, new, agent_type=AUTO)
    with pytest.raises(InvalidTransition):
        check_agent_transition(old, new, agent_type=AUTO)


def test_resume_returns_to_the_remembered_state_only() -> None:
    assert agent_transition_allowed(A.PAUSED, A.REVIEWING, agent_type=AUTO, paused_from=A.REVIEWING)
    assert not agent_transition_allowed(
        A.PAUSED, A.WORKING, agent_type=AUTO, paused_from=A.REVIEWING
    )
    assert agent_transition_allowed(A.PAUSED, A.IDLE, agent_type=AUTO, paused_from=A.WORKING)


def test_completed_and_failed_are_terminal_for_subagents_only() -> None:
    for terminal in (A.COMPLETED, A.FAILED):
        assert agent_transition_allowed(terminal, A.IDLE, agent_type=AUTO)
        assert not agent_transition_allowed(terminal, A.IDLE, agent_type=SUB)
    assert not agent_transition_allowed(A.COMPLETED, A.FAILED, agent_type=SUB)
    assert agent_transition_allowed(A.COMPLETED, A.FAILED, agent_type=AUTO)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (T.CREATED, T.QUEUED),
        (T.QUEUED, T.RUNNING),
        (T.RUNNING, T.COMPLETED),
        (T.RUNNING, T.WAITING_APPROVAL),
        (T.WAITING_APPROVAL, T.RUNNING),
        (T.WAITING_APPROVAL, T.CANCELLED),
        (T.RUNNING, T.WAITING),
        (T.WAITING, T.RUNNING),
        (T.RUNNING, T.FAILED),
        (T.CREATED, T.CANCELLED),
        (T.QUEUED, T.CANCELLED),
        (T.RUNNING, T.CANCELLED),
        (T.WAITING, T.CANCELLED),
        (T.RUNNING, T.QUEUED),  # recovery: safe to resume
    ],
)
def test_spec_task_transitions_are_allowed(old: T, new: T) -> None:
    assert task_transition_allowed(old, new)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (T.CREATED, T.RUNNING),
        (T.CREATED, T.COMPLETED),
        (T.QUEUED, T.COMPLETED),
        (T.FAILED, T.RUNNING),  # retry creates a NEW task
        (T.FAILED, T.QUEUED),
        (T.COMPLETED, T.RUNNING),
        (T.CANCELLED, T.QUEUED),
        (T.COMPLETED, T.CANCELLED),
    ],
)
def test_invalid_task_transitions_are_rejected(old: T, new: T) -> None:
    with pytest.raises(InvalidTransition):
        check_task_transition(old, new)
