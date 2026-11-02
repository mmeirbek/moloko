"""Creates subagents + their subtasks from a validated plan — within the limits (spec 14.3, 7.2)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.engine import agent_payload, task_payload
from app.agents.state import AgentStatus, AgentType, TaskStatus, TaskType
from app.core.config import Settings
from app.events import bus
from app.models.agent import Agent
from app.models.task import Task
from app.orchestrator.plan import Plan, SubtaskSpec
from app.orchestrator.prompts import review_instructions, subagent_system


class DepthLimitExceeded(Exception):
    def __init__(self, depth: int, limit: int) -> None:
        super().__init__(f"subagent depth {depth} exceeds the limit of {limit}")
        self.depth = depth
        self.limit = limit


def child_depth(parent: Agent, settings: Settings) -> int:
    depth = parent.depth + 1
    if depth > settings.max_subagent_depth:
        raise DepthLimitExceeded(depth, settings.max_subagent_depth)
    return depth


def root_run_id(orchestrator: Agent, task: Task) -> uuid.UUID:
    """The run that owns the whole tree: the root orchestrator's run."""
    if orchestrator.agent_type == AgentType.SUBAGENT.value and orchestrator.run_id is not None:
        return orchestrator.run_id
    assert task.run_id is not None
    return task.run_id


async def create_subagent(
    db: AsyncSession,
    *,
    parent: Agent,
    root_run: uuid.UUID,
    spec: SubtaskSpec,
    settings: Settings,
    system_prompt: str | None = None,
) -> Agent:
    depth = child_depth(parent, settings)
    can_delegate = spec.delegate and depth < settings.max_subagent_depth
    agent = Agent(
        user_id=parent.user_id,
        name=f"{spec.specialization.replace('_', ' ').title()} · {spec.key}",
        description=spec.title,
        agent_type=AgentType.SUBAGENT.value,
        specialization=spec.specialization,
        model_config_id=parent.model_config_id,  # ⟨M⟩: never a model name chosen by the plan
        system_prompt=system_prompt or subagent_system(spec.specialization, spec.instructions),
        # ⟨T⟩: never a tool its orchestrator lacks (no privilege escalation).
        allowed_tools=[t for t in dict.fromkeys(spec.tools) if t in parent.allowed_tools],
        autonomy_level=parent.autonomy_level,
        permissions=dict(parent.permissions or {}),  # per-tool overrides are inherited
        status=AgentStatus.IDLE.value,
        parent_agent_id=parent.id,
        run_id=root_run,
        depth=depth,
        limits=dict(parent.limits or {}),
        memory_settings={},
        runtime="orchestrator" if can_delegate else "native",
    )
    db.add(agent)
    await db.flush()
    await bus.emit(
        db,
        user_id=agent.user_id,
        type="agent.created",
        agent_id=agent.id,
        run_id=root_run,
        payload={"agent": agent_payload(agent), "parent_agent_id": str(parent.id)},
    )
    return agent


MAX_ROSTER = 20


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


async def create_subtasks(
    db: AsyncSession,
    *,
    orchestrator: Agent,
    parent_task: Task,
    plan: Plan,
    settings: Settings,
) -> list[Task]:
    root = root_run_id(orchestrator, parent_task)
    tasks_by_key: dict[str, Task] = {}
    roster = {a.name: a for a in await owner_agents(db, orchestrator.user_id)}
    for spec in plan.subtasks:
        extra: dict[str, object] = {"key": spec.key, "specialization": spec.specialization}
        assigned = roster.get(spec.agent) if spec.agent else None
        if assigned is not None:
            # A persistent agent takes this part: no subagent; the task records its run tree.
            worker_id = assigned.id
            extra.update(assigned=True, root_run=str(root), specialization=assigned.specialization)
        else:
            sub = await create_subagent(
                db, parent=orchestrator, root_run=root, spec=spec, settings=settings
            )
            worker_id = sub.id
        task = Task(
            user_id=orchestrator.user_id,
            title=spec.title,
            description=spec.instructions,
            task_type=TaskType.SUBTASK.value,
            status=TaskStatus.CREATED.value,
            priority=parent_task.priority,
            agent_id=worker_id,
            parent_task_id=parent_task.id,
            created_by="agent",
            depends_on=[],
            extra=extra,
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


async def create_review_task(
    db: AsyncSession,
    *,
    orchestrator: Agent,
    parent_task: Task,
    inputs: list[Task],
    settings: Settings,
) -> Task:
    spec = SubtaskSpec(
        key="review", title=f"Review: {parent_task.title}"[:200], specialization="reviewer"
    )
    root = root_run_id(orchestrator, parent_task)
    reviewer = await create_subagent(
        db,
        parent=orchestrator,
        root_run=root,
        spec=spec,
        settings=settings,
        system_prompt=subagent_system("reviewer", review_instructions()),
    )
    task = Task(
        user_id=orchestrator.user_id,
        title=spec.title,
        description=f"Review the results for: {parent_task.title}",
        task_type=TaskType.REVIEW.value,
        status=TaskStatus.CREATED.value,
        priority=parent_task.priority,
        agent_id=reviewer.id,
        parent_task_id=parent_task.id,
        created_by="agent",
        depends_on=[str(t.id) for t in inputs],
        extra={"key": "review", "specialization": "reviewer"},
    )
    db.add(task)
    await db.flush()
    await bus.emit(
        db,
        user_id=task.user_id,
        type="task.created",
        agent_id=reviewer.id,
        task_id=task.id,
        run_id=root,
        payload={"task": task_payload(task)},
    )
    return task
