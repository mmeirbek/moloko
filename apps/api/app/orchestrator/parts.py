"""Turns a validated plan into parts for the owner's persistent agents (spec 14.3, owner's
decision: no temporary subagents). An agent the plan describes in ``new_agents`` is
created first — a regular agent of the office that stays after the task."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.engine import agent_payload, task_payload
from app.agents.looks import pick_animal
from app.agents.state import AgentStatus, AgentType, TaskStatus, TaskType
from app.events import bus
from app.models.agent import Agent
from app.models.provider import ModelConfig, Provider
from app.models.task import Task
from app.orchestrator.plan import NewAgentSpec, Plan
from app.orchestrator.prompts import new_agent_system
from app.providers.model_profiles import describe, profile_for
from app.repositories.users import UserRepository
from app.services.audit import AuditService

MAX_ROSTER = 20


def root_run_id(task: Task) -> uuid.UUID:
    """The run that owns the whole tree: the Orchestrator's run."""
    assert task.run_id is not None
    return task.run_id


async def owner_agents(db: AsyncSession, user_id: uuid.UUID) -> list[Agent]:
    """The owner's persistent agents the Orchestrator may give parts of a plan to."""
    rows = await db.execute(
        select(Agent)
        .where(
            Agent.user_id == user_id,
            Agent.agent_type == AgentType.AUTONOMOUS.value,
            Agent.archived_at.is_(None),
        )
        .order_by(Agent.created_at)
        .limit(MAX_ROSTER)
    )
    return list(rows.scalars())


async def _free_name(db: AsyncSession, user_id: uuid.UUID, base: str) -> str:
    taken = set(
        (
            await db.execute(
                select(Agent.name).where(Agent.user_id == user_id, Agent.archived_at.is_(None))
            )
        ).scalars()
    )
    name, n = base[:100], 2
    while name in taken:
        name, n = f"{base[: 100 - len(str(n)) - 1]} {n}", n + 1
    return name


async def create_agent(
    db: AsyncSession, *, orchestrator: Agent, spec: NewAgentSpec, task: Task
) -> Agent:
    """A new persistent agent for the owner's office. Never more rights than the
    Orchestrator: its model, its autonomy level and per-tool rules, only its tools — unless
    the owner turned on «Полный доступ всем агентам», which covers every agent of the office,
    this one included (owner's decision 2026-11-03)."""
    agent = Agent(
        user_id=orchestrator.user_id,
        name=await _free_name(db, orchestrator.user_id, spec.name),
        description=spec.description,
        agent_type=AgentType.AUTONOMOUS.value,
        specialization=spec.specialization,
        model_config_id=uuid.UUID(spec.model) if spec.model else orchestrator.model_config_id,
        system_prompt=new_agent_system(spec.specialization, spec.instructions),
        allowed_tools=[t for t in dict.fromkeys(spec.tools) if t in orchestrator.allowed_tools],
        autonomy_level=orchestrator.autonomy_level,
        permissions={"tools": dict((orchestrator.permissions or {}).get("tools") or {})},
        status=AgentStatus.IDLE.value,
        limits=dict(orchestrator.limits or {}),
        memory_settings={},
        animal=await pick_animal(db, orchestrator.user_id),  # the Orchestrator picks at random
    )
    if await UserRepository(db).full_access_for_all(agent.user_id):
        agent.full_access_since = datetime.now(UTC)
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    await bus.emit(
        db,
        user_id=agent.user_id,
        type="agent.created",
        agent_id=agent.id,
        task_id=task.id,
        payload={"agent": agent_payload(agent), "created_by": "orchestrator"},
    )
    await AuditService(db).record(
        "agent.created",
        "success",
        actor_type="agent",
        actor_id=orchestrator.id,
        user_id=agent.user_id,
        resource_type="agent",
        resource_id=str(agent.id),
        details={
            "name": agent.name,
            "type": agent.agent_type,
            "autonomy": agent.autonomy_level,
            "tools": agent.allowed_tools,
            **({"full_access": "all"} if agent.full_access else {}),
            "created_by": "orchestrator",
            "task_id": str(task.id),
        },
    )
    return agent


async def owner_models(
    db: AsyncSession, user_id: uuid.UUID, limit: int
) -> dict[str, tuple[str, str]]:
    """The owner's enabled models for the Orchestrator to choose from: name → (its line in the
    plan prompt with what it is best at, its model config id). At most ``limit``
    (ORCHESTRATOR_MAX_MODELS_LISTED), the strongest first, so the prompt stays short."""
    rows = (
        await db.execute(
            select(ModelConfig, Provider.name)
            .join(Provider, ModelConfig.provider_id == Provider.id)
            .where(
                ModelConfig.user_id == user_id,
                ModelConfig.enabled.is_(True),
                Provider.enabled.is_(True),
            )
        )
    ).all()
    ranked = sorted(
        rows, key=lambda r: (profile_for(r[0].model).tier, profile_for(r[0].model).speed)
    )
    out: dict[str, tuple[str, str]] = {}
    for config, provider_name in ranked[:limit]:
        name = f"{config.model} @ {provider_name}"
        out[name] = (describe(name, config.model), str(config.id))
    return out


async def create_subtasks(
    db: AsyncSession, *, orchestrator: Agent, parent_task: Task, plan: Plan
) -> list[Task]:
    """One task per part, each for a persistent agent; new agents are created first."""
    root = root_run_id(parent_task)
    by_name = {a.name: a for a in await owner_agents(db, orchestrator.user_id)}
    for new in plan.new_agents:
        by_name[new.name] = await create_agent(
            db, orchestrator=orchestrator, spec=new, task=parent_task
        )
    tasks_by_key: dict[str, Task] = {}
    for spec in plan.subtasks:
        worker = by_name[spec.agent]
        task = Task(
            user_id=orchestrator.user_id,
            title=spec.title,
            description=spec.instructions,
            task_type=TaskType.SUBTASK.value,
            status=TaskStatus.CREATED.value,
            priority=parent_task.priority,
            agent_id=worker.id,
            parent_task_id=parent_task.id,
            created_by="agent",
            depends_on=[],
            extra={
                "key": spec.key,
                "assigned": True,
                "root_run": str(root),
                "specialization": worker.specialization,
                # the model the Orchestrator picked for this part (runtimes/native.py)
                **({"model_config_id": spec.model} if spec.model else {}),
            },
        )
        db.add(task)
        tasks_by_key[spec.key] = task
    await db.flush()
    for spec in plan.subtasks:
        tasks_by_key[spec.key].depends_on = [str(tasks_by_key[k].id) for k in spec.depends_on]
    for task in tasks_by_key.values():
        await bus.emit(
            db,
            user_id=task.user_id,
            type="task.created",
            agent_id=task.agent_id,
            task_id=task.id,
            run_id=root,
            payload={"task": task_payload(task)},
        )
    return list(tasks_by_key.values())
