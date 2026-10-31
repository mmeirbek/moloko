"""Starting orchestrated runs and reading run trees (Subagent Office, chat hand-off)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.engine import agent_payload
from app.agents.state import ACTIVE_TASK, AgentStatus, AgentType, TaskType
from app.core.errors import NotFound
from app.events import bus
from app.models.agent import Agent, AgentRun
from app.models.agent_message import AgentMessage
from app.models.chat import Conversation, Message
from app.models.task import Task
from app.orchestrator.scheduler import tree_tasks
from app.services.audit import AuditService
from app.services.chat import DEFAULT_TITLE, GenerationInProgress, make_title
from app.services.tasks import TaskService
from app.tasks.queue import TaskEnqueuer

ORCHESTRATOR_NAME = "Orchestrator"


async def ensure_orchestrator(db: AsyncSession, user_id: uuid.UUID) -> Agent:
    existing = (
        await db.execute(
            select(Agent)
            .where(
                Agent.user_id == user_id,
                Agent.agent_type == AgentType.ORCHESTRATOR.value,
                Agent.archived_at.is_(None),
            )
            .order_by(Agent.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    agent = Agent(
        user_id=user_id,
        name=ORCHESTRATOR_NAME,
        description="Splits complex tasks and coordinates subagents.",
        agent_type=AgentType.ORCHESTRATOR.value,
        system_prompt="",
        autonomy_level="supervised",
        allowed_tools=[],
        permissions={},
        status=AgentStatus.IDLE.value,
        limits={},
        memory_settings={},
        runtime="orchestrator",
    )
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    await bus.emit(
        db,
        user_id=user_id,
        type="agent.created",
        agent_id=agent.id,
        payload={"agent": agent_payload(agent)},
    )
    await AuditService(db).record(
        "agent.created",
        "success",
        actor_type="system",
        user_id=user_id,
        resource_type="agent",
        resource_id=str(agent.id),
        details={"name": agent.name, "type": agent.agent_type},
    )
    await bus.commit(db)
    return agent


async def start_orchestrated_run(
    db: AsyncSession,
    queue: TaskEnqueuer | None,
    user_id: uuid.UUID,
    *,
    title: str,
    description: str,
    conversation_id: uuid.UUID | None = None,
) -> tuple[Task, AgentRun]:
    orchestrator = await ensure_orchestrator(db, user_id)
    service = TaskService(db, queue)
    from app.schemas.tasks import TaskCreate

    task = await service.create(
        user_id,
        TaskCreate(title=title, description=description, agent_id=orchestrator.id, start=False),
    )
    return await service.start(user_id, task.id, conversation_id=conversation_id)


async def hand_off_chat(
    db: AsyncSession,
    queue: TaskEnqueuer | None,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    content: str,
    *,
    title_chars: int,
) -> tuple[Message, Task, AgentRun]:
    """Chat → agents: the question is saved in the chat, the Orchestrator takes it, and
    the final answer is posted back into the conversation when the run ends."""
    conv = (
        await db.execute(
            select(Conversation).where(Conversation.id == conversation_id).with_for_update()
        )
    ).scalar_one_or_none()
    if conv is None or conv.user_id != user_id:
        raise NotFound("Conversation not found.")
    busy = await db.execute(
        select(Message.id)
        .where(Message.conversation_id == conversation_id, Message.status == "streaming")
        .limit(1)
    )
    if busy.first() is not None:
        raise GenerationInProgress()
    title = make_title(content, title_chars)
    if conv.title == DEFAULT_TITLE:
        conv.title = title
    now = datetime.now(UTC)
    conv.last_message_at = now
    await db.commit()
    task, run = await start_orchestrated_run(
        db, queue, user_id, title=title, description=content, conversation_id=conversation_id
    )
    message = Message(
        conversation_id=conversation_id,
        user_id=user_id,
        role="user",
        content=content,
        status="completed",
        agent_run_id=run.id,
        created_at=now,
        completed_at=now,
    )
    db.add(message)
    await db.commit()
    return message, task, run


async def get_run(db: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID) -> AgentRun:
    run = await db.get(AgentRun, run_id)
    if run is None or run.user_id != user_id:
        raise NotFound("Run not found.")
    return run


async def run_tree(
    db: AsyncSession, run: AgentRun
) -> tuple[list[Agent], list[Task], list[AgentMessage]]:
    agents = list(
        (
            await db.execute(
                select(Agent)
                .where(Agent.run_id == run.id, Agent.agent_type == AgentType.SUBAGENT.value)
                .order_by(Agent.created_at)
            )
        ).scalars()
    )
    tasks = await tree_tasks(db, run.id)
    messages = list(
        (
            await db.execute(
                select(AgentMessage)
                .where(AgentMessage.run_id == run.id)
                .order_by(AgentMessage.created_at)
            )
        ).scalars()
    )
    return agents, tasks, messages


async def list_orchestrated_runs(
    db: AsyncSession, user_id: uuid.UUID, *, active_only: bool, limit: int
) -> list[AgentRun]:
    query = (
        select(AgentRun)
        .join(Agent, Agent.id == AgentRun.agent_id)
        .join(Task, Task.id == AgentRun.task_id)
        .where(
            AgentRun.user_id == user_id,
            Agent.agent_type == AgentType.ORCHESTRATOR.value,
            Task.task_type == TaskType.USER.value,
        )
    )
    if active_only:
        query = query.where(AgentRun.status.in_([s.value for s in ACTIVE_TASK]))
    return list(
        (await db.execute(query.order_by(AgentRun.created_at.desc()).limit(limit))).scalars()
    )
