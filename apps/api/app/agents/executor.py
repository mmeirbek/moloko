"""Runs one task: claim it atomically, pick the runtime, run, then notify listeners."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.control import RunControl
from app.agents.engine import lock_agent, lock_run, lock_task, set_agent_status, set_task_status
from app.agents.state import AgentStatus, TaskStatus
from app.core.config import Settings
from app.core.errors import NotFound, new_error_id
from app.events import bus
from app.models.agent import Agent
from app.providers.gateway import ModelGateway
from app.runtimes.base import AgentRuntime, RunContext
from app.runtimes.native import NativeRuntime
from app.sandbox.base import Sandbox

logger = logging.getLogger("moloko.executor")

# Called after a task's runtime returned (e.g. to schedule the parent's next step).
AfterTaskHook = Callable[[uuid.UUID], Awaitable[None]]


class Executor:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        gateway: ModelGateway,
        settings: Settings,
        *,
        runtimes: dict[str, AgentRuntime] | None = None,
        after_task: AfterTaskHook | None = None,
        sandbox: Sandbox | None = None,
    ) -> None:
        self.sessionmaker = sessionmaker
        self.gateway = gateway
        self.settings = settings
        self.sandbox = sandbox
        self.runtimes: dict[str, AgentRuntime] = runtimes or {"native": NativeRuntime()}
        self.after_task = after_task

    def runtime_for(self, agent: Agent) -> AgentRuntime:
        native = self.runtimes["native"]
        if agent.agent_type == "orchestrator" or agent.runtime == "orchestrator":
            return self.runtimes.get("orchestrator", native)
        if agent.agent_type == "subagent":
            return self.runtimes.get("subagent", native)
        return self.runtimes.get(agent.runtime, native)

    async def _claim(self, task_id: uuid.UUID) -> tuple[RunContext, AgentRuntime] | None:
        async with self.sessionmaker() as db:
            try:
                task = await lock_task(db, task_id)
            except NotFound:
                return None
            if TaskStatus(task.status) != TaskStatus.QUEUED:
                return None  # duplicate or obsolete job: another copy handled it
            if task.agent_id is None or task.run_id is None:
                await set_task_status(
                    db,
                    task,
                    TaskStatus.CANCELLED,
                    reason="no_agent",
                )
                await bus.commit(db)
                return None
            agent = await lock_agent(db, task.agent_id)
            run = await lock_run(db, task.run_id)
            fresh = not run.state.get("messages") and run.steps == 0 and not run.plan
            await set_task_status(
                db, task, TaskStatus.RUNNING, reason="resumed" if not fresh else None, run=run
            )
            agent.current_task_id = task.id
            status = AgentStatus(agent.status)
            if status in (AgentStatus.IDLE, AgentStatus.COMPLETED, AgentStatus.FAILED):
                if status != AgentStatus.IDLE:
                    await set_agent_status(db, agent, AgentStatus.IDLE, reason="new_task")
                await set_agent_status(db, agent, AgentStatus.PLANNING, reason="task_started")
            if fresh:
                await bus.emit(
                    db,
                    user_id=task.user_id,
                    type="agent.task_started",
                    agent_id=agent.id,
                    task_id=task.id,
                    run_id=run.id,
                    payload={"title": task.title},
                )
            await bus.commit(db)
            ctx = RunContext(
                run_id=run.id,
                task_id=task.id,
                agent_id=agent.id,
                user_id=task.user_id,
                fresh=fresh,
                sessionmaker=self.sessionmaker,
                gateway=self.gateway,
                settings=self.settings,
                control=RunControl(
                    self.sessionmaker, task.id, agent.id, self.settings.worker_control_poll_seconds
                ),
                sandbox=self.sandbox,
            )
            return ctx, self.runtime_for(agent)

    async def execute(self, task_id: uuid.UUID) -> None:
        claimed = await self._claim(task_id)
        if claimed is None:
            return
        ctx, runtime = claimed
        logger.info("run_started", extra={"task_id": str(task_id), "runtime": runtime.name})
        await runtime.start(ctx)
        if self.after_task is not None:
            try:
                await self.after_task(task_id)
            except Exception:
                logger.exception(
                    "after_task_hook_failed",
                    extra={"task_id": str(task_id), "error_id": new_error_id()},
                )
