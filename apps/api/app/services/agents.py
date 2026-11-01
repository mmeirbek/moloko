"""Agent Manager (spec 14): profiles and run control (run / pause / resume / stop)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.engine import (
    agent_is_busy,
    agent_payload,
    lock_agent,
    lock_task,
    release_agent,
    set_agent_status,
    set_task_status,
)
from app.agents.state import (
    ACTIVE_AGENT,
    AgentStatus,
    AgentType,
    InvalidTransition,
    TaskStatus,
    agent_transition_allowed,
)
from app.core.config import Settings
from app.core.errors import AppError, NotFound
from app.events import bus
from app.models.agent import Agent, AgentRun
from app.models.provider import ModelConfig
from app.models.task import Task
from app.providers.gateway import ModelUnavailable
from app.schemas.agents import (
    AgentCreate,
    AgentLimits,
    AgentRunRequest,
    AgentUpdate,
    MemorySettings,
)
from app.schemas.tasks import TaskCreate
from app.services.audit import AuditService
from app.services.system import ensure_engine_running
from app.services.tasks import AgentBusy, TaskService
from app.tasks.queue import TaskEnqueuer


class LimitTooHigh(AppError):
    status_code = 422
    code = "limit_too_high"
    message = "A per-agent limit can only be stricter than the global one."


class AgentService:
    def __init__(
        self, db: AsyncSession, queue: TaskEnqueuer | None, settings: Settings | None = None
    ) -> None:
        self.db = db
        self.queue = queue
        self.settings = settings
        self.tasks = TaskService(db, queue)
        self.audit = AuditService(db)

    async def get(self, user_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
        agent = await self.db.get(Agent, agent_id)
        if agent is None or agent.user_id != user_id:
            raise NotFound("Agent not found.")
        return agent

    async def list_agents(
        self,
        user_id: uuid.UUID,
        *,
        agent_type: AgentType | None,
        include_archived: bool,
        run_id: uuid.UUID | None,
    ) -> list[Agent]:
        query = select(Agent).where(Agent.user_id == user_id)
        if agent_type is not None:
            query = query.where(Agent.agent_type == agent_type.value)
        if run_id is not None:
            query = query.where(Agent.run_id == run_id)
        if not include_archived:
            query = query.where(Agent.archived_at.is_(None))
        return list((await self.db.execute(query.order_by(Agent.created_at))).scalars())

    async def _check_model(self, user_id: uuid.UUID, model_config_id: uuid.UUID | None) -> None:
        if model_config_id is None:
            return
        config = await self.db.get(ModelConfig, model_config_id)
        if config is None or config.user_id != user_id:
            raise ModelUnavailable("The selected model does not exist.")

    def _check_limits(self, limits: AgentLimits | None, memory: MemorySettings | None) -> None:
        """Per-agent limits may only be stricter than the global ones (spec 7.2, 14.2)."""
        if self.settings is None:
            return
        caps = {
            "max_steps": (limits.max_steps if limits else None, self.settings.max_steps_per_run),
            "run_timeout_seconds": (
                limits.run_timeout_seconds if limits else None,
                self.settings.run_timeout_seconds,
            ),
            "max_context_chars": (
                memory.max_context_chars if memory else None,
                self.settings.memory_context_max_chars,
            ),
        }
        for name, (value, cap) in caps.items():
            if value is not None and value > cap:
                raise LimitTooHigh(
                    f"{name} can be at most {cap} (the global limit).",
                    details={"field": name, "max": cap},
                )

    async def create(self, user_id: uuid.UUID, data: AgentCreate) -> Agent:
        if data.agent_type == AgentType.SUBAGENT:
            raise InvalidTransition("Subagents are created by the Orchestrator, not by hand.")
        self._check_limits(data.limits, data.memory_settings)
        await self._check_model(user_id, data.model_config_id)
        agent = Agent(
            user_id=user_id,
            name=data.name,
            description=data.description,
            agent_type=data.agent_type.value,
            specialization=data.specialization,
            model_config_id=data.model_config_id,
            system_prompt=data.system_prompt,
            autonomy_level=data.autonomy_level.value,
            allowed_tools=list(dict.fromkeys(data.allowed_tools)),
            permissions={},
            status=AgentStatus.IDLE.value,
            limits=data.limits.model_dump(exclude_none=True),
            memory_settings=data.memory_settings.model_dump(exclude_defaults=True),
        )
        self.db.add(agent)
        await self.db.flush()
        await self.db.refresh(agent)
        await bus.emit(
            self.db,
            user_id=user_id,
            type="agent.created",
            agent_id=agent.id,
            payload={"agent": agent_payload(agent)},
        )
        await self.audit.record(
            "agent.created",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="agent",
            resource_id=str(agent.id),
            details={
                "name": agent.name,
                "type": agent.agent_type,
                "autonomy": agent.autonomy_level,
            },
        )
        await bus.commit(self.db)
        return agent

    async def update(self, user_id: uuid.UUID, agent_id: uuid.UUID, data: AgentUpdate) -> Agent:
        agent = await lock_agent(self.db, agent_id)
        if agent.user_id != user_id or agent.archived_at is not None:
            raise NotFound("Agent not found.")
        self._check_limits(data.limits, data.memory_settings)
        changed: list[str] = []
        fields = data.model_fields_set
        for name in ("name", "description", "system_prompt"):
            value = getattr(data, name)
            if value is not None and value != getattr(agent, name):
                setattr(agent, name, value)
                changed.append(name)
        if "specialization" in fields and data.specialization != agent.specialization:
            agent.specialization = data.specialization
            changed.append("specialization")
        if "model_config_id" in fields and data.model_config_id != agent.model_config_id:
            await self._check_model(user_id, data.model_config_id)
            agent.model_config_id = data.model_config_id
            changed.append("model_config_id")
        if data.autonomy_level is not None and data.autonomy_level.value != agent.autonomy_level:
            agent.autonomy_level = data.autonomy_level.value
            changed.append("autonomy_level")
        if data.allowed_tools is not None:
            tools = list(dict.fromkeys(data.allowed_tools))
            if tools != agent.allowed_tools:
                agent.allowed_tools = tools
                changed.append("allowed_tools")
        if data.limits is not None:
            limits = data.limits.model_dump(exclude_none=True)
            if limits != agent.limits:
                agent.limits = limits
                changed.append("limits")
        if data.memory_settings is not None:
            memory_settings = data.memory_settings.model_dump(exclude_defaults=True)
            if memory_settings != agent.memory_settings:
                agent.memory_settings = memory_settings
                changed.append("memory_settings")
        if changed:
            agent.config_version += 1
            agent.updated_at = datetime.now(UTC)
            await bus.emit(
                self.db,
                user_id=user_id,
                type="agent.updated",
                agent_id=agent.id,
                payload={"changed": changed, "agent": agent_payload(agent)},
            )
            await self.audit.record(
                "agent.updated",
                "success",
                actor_type="user",
                actor_id=user_id,
                user_id=user_id,
                resource_type="agent",
                resource_id=str(agent.id),
                details={"changed": changed},
            )
        await bus.commit(self.db)
        return agent

    async def archive(self, user_id: uuid.UUID, agent_id: uuid.UUID) -> None:
        """DELETE keeps history: the profile is archived, its runs and tasks stay."""
        agent = await lock_agent(self.db, agent_id)
        if agent.user_id != user_id or agent.archived_at is not None:
            raise NotFound("Agent not found.")
        if agent_is_busy(agent):
            raise AgentBusy("Stop the agent before deleting it.")
        agent.archived_at = datetime.now(UTC)
        await bus.emit(
            self.db,
            user_id=user_id,
            type="agent.updated",
            agent_id=agent.id,
            payload={"changed": ["archived_at"], "agent": agent_payload(agent)},
        )
        await self.audit.record(
            "agent.deleted",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="agent",
            resource_id=str(agent.id),
        )
        await bus.commit(self.db)

    # --- run control ---------------------------------------------------------------------

    async def run(
        self, user_id: uuid.UUID, agent_id: uuid.UUID, req: AgentRunRequest
    ) -> tuple[Task, AgentRun]:
        await ensure_engine_running(self.db, user_id)
        agent = await self.get(user_id, agent_id)
        if agent.agent_type == AgentType.SUBAGENT.value:
            raise InvalidTransition("Subagents are run by their Orchestrator.")
        if req.task_id is not None:
            task = await self.tasks.get(user_id, req.task_id)
            if task.agent_id not in (None, agent.id):
                raise InvalidTransition("This task is assigned to another agent.")
            if task.agent_id is None:
                task.agent_id = agent.id
                await bus.commit(self.db)
        else:
            if not req.title:
                raise InvalidTransition("Give the task a title.")
            task = await self.tasks.create(
                user_id,
                TaskCreate(
                    title=req.title, description=req.description, agent_id=agent.id, start=False
                ),
            )
        return await self.tasks.start(user_id, task.id)

    async def _current_task(self, agent: Agent) -> Task | None:
        return await lock_task(self.db, agent.current_task_id) if agent.current_task_id else None

    async def pause(self, user_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
        agent = await lock_agent(self.db, agent_id)
        if agent.user_id != user_id:
            raise NotFound("Agent not found.")
        if AgentStatus(agent.status) not in ACTIVE_AGENT:
            raise InvalidTransition("Only a working agent can be paused.")
        await set_agent_status(self.db, agent, AgentStatus.PAUSED, reason="paused_by_user")
        task = await self._current_task(agent)
        if task is not None and TaskStatus(task.status) in (TaskStatus.RUNNING, TaskStatus.QUEUED):
            run = await self.db.get(AgentRun, task.run_id) if task.run_id else None
            if TaskStatus(task.status) == TaskStatus.RUNNING:
                await set_task_status(self.db, task, TaskStatus.WAITING, reason="paused", run=run)
        await self.audit.record(
            "agent.paused",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="agent",
            resource_id=str(agent.id),
        )
        await bus.commit(self.db)
        return agent

    async def resume(self, user_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
        await ensure_engine_running(self.db, user_id)
        agent = await lock_agent(self.db, agent_id)
        if agent.user_id != user_id:
            raise NotFound("Agent not found.")
        task = await self._current_task(agent)
        if AgentStatus(agent.status) == AgentStatus.PAUSED:
            await set_agent_status(
                self.db,
                agent,
                AgentStatus(agent.paused_from or AgentStatus.WORKING),
                reason="resumed_by_user",
            )
        elif not (task is not None and TaskStatus(task.status) == TaskStatus.WAITING):
            raise InvalidTransition("This agent is not paused or waiting.")
        requeue = False
        if task is not None and TaskStatus(task.status) == TaskStatus.WAITING:
            run = await self.db.get(AgentRun, task.run_id) if task.run_id else None
            await set_task_status(self.db, task, TaskStatus.QUEUED, reason="resumed", run=run)
            requeue = True
        await self.audit.record(
            "agent.resumed",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="agent",
            resource_id=str(agent.id),
        )
        await bus.commit(self.db)
        if requeue and task is not None and self.queue is not None:
            await self.queue.enqueue_task(task.id)
        return agent

    async def stop(self, user_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
        agent = await lock_agent(self.db, agent_id)
        if agent.user_id != user_id:
            raise NotFound("Agent not found.")
        task = await self._current_task(agent)
        if task is not None and TaskStatus(task.status) not in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        ):
            await self.tasks._cancel_tree(task, "agent_stopped")
        elif agent_transition_allowed(
            AgentStatus(agent.status),
            AgentStatus.IDLE,
            agent_type=AgentType(agent.agent_type),
            paused_from=AgentStatus(agent.paused_from) if agent.paused_from else None,
        ):
            await release_agent(self.db, agent, to=AgentStatus.IDLE, reason="agent_stopped")
        await self.audit.record(
            "agent.stopped",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="agent",
            resource_id=str(agent.id),
        )
        await bus.commit(self.db)
        await self.db.refresh(agent)
        return agent
