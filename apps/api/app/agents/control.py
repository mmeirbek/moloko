"""Cooperative cancel / pause for a running agent.

The database is the source of truth: cancel and pause are status changes written by
the API. A running agent re-reads them between steps and while waiting on a model
call (every WORKER_CONTROL_POLL_SECONDS), and abandons the in-flight call if needed.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable
from enum import StrEnum
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.state import AgentStatus, TaskStatus
from app.models.agent import Agent
from app.models.task import Task

T = TypeVar("T")


class Signal(StrEnum):
    RUN = "run"
    CANCEL = "cancel"
    PAUSE = "pause"


class Interrupted(Exception):
    def __init__(self, signal: Signal) -> None:
        self.signal = signal
        super().__init__(signal.value)


class RunControl:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        task_id: uuid.UUID,
        agent_id: uuid.UUID,
        poll_seconds: float,
    ) -> None:
        self.sessionmaker = sessionmaker
        self.task_id = task_id
        self.agent_id = agent_id
        self.poll_seconds = poll_seconds

    async def signal(self) -> Signal:
        async with self.sessionmaker() as db:
            row = (
                await db.execute(
                    select(Task.status, Task.status_reason, Agent.status)
                    .join(Agent, Agent.id == Task.agent_id)
                    .where(Task.id == self.task_id)
                )
            ).first()
        if row is None:
            return Signal.CANCEL
        task_status, reason, agent_status = row
        if task_status in (TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.COMPLETED):
            return Signal.CANCEL
        if agent_status == AgentStatus.PAUSED or (
            task_status == TaskStatus.WAITING and reason == "paused"
        ):
            return Signal.PAUSE
        if task_status != TaskStatus.RUNNING:
            return Signal.CANCEL  # someone else took over (e.g. re-queued); stop this copy
        return Signal.RUN

    async def check(self) -> None:
        signal = await self.signal()
        if signal != Signal.RUN:
            raise Interrupted(signal)

    async def guard(self, awaitable: Awaitable[T]) -> T:
        """Await ``awaitable`` but abandon it as soon as the run is cancelled or paused."""
        work = asyncio.ensure_future(awaitable)
        try:
            while True:
                done, _ = await asyncio.wait({work}, timeout=self.poll_seconds)
                if done:
                    return work.result()
                signal = await self.signal()
                if signal != Signal.RUN:
                    work.cancel()
                    raise Interrupted(signal)
        finally:
            if not work.done():
                work.cancel()
