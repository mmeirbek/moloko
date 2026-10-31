"""Task Manager (spec 9): create, assign, start, cancel, retry, history."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.engine import (
    agent_is_busy,
    lock_agent,
    lock_task,
    release_agent,
    set_agent_status,
    set_task_status,
    task_payload,
)
from app.agents.state import (
    ACTIVE_TASK,
    AgentStatus,
    AgentType,
    InvalidTransition,
    TaskStatus,
    TaskType,
)
from app.core.errors import Conflict, NotFound
from app.events import bus
from app.models.agent import Agent, AgentRun
from app.models.event import AgentEvent
from app.models.task import Task
from app.schemas.common import decode_cursor, encode_cursor
from app.schemas.tasks import TaskCreate, TaskFilter, TaskUpdate
from app.services.audit import AuditService
from app.services.system import ensure_engine_running
from app.tasks.queue import TaskEnqueuer


class AgentBusy(Conflict):
    code = "agent_busy"
    message = "This agent is already working on a task."


class AgentArchived(Conflict):
    code = "agent_archived"
    message = "This agent was deleted."


_FILTERS: dict[str, list[str]] = {
    "active": [s.value for s in ACTIVE_TASK],
    "completed": [TaskStatus.COMPLETED.value],
    "failed": [TaskStatus.FAILED.value],
    "cancelled": [TaskStatus.CANCELLED.value],
}


class TaskService:
    def __init__(self, db: AsyncSession, queue: TaskEnqueuer | None) -> None:
        self.db = db
        self.queue = queue
        self.audit = AuditService(db)

    async def get(self, user_id: uuid.UUID, task_id: uuid.UUID) -> Task:
        task = await self.db.get(Task, task_id)
        if task is None or task.user_id != user_id:
            raise NotFound("Task not found.")
        return task

    async def list_tasks(
        self,
        user_id: uuid.UUID,
        *,
        status: TaskFilter,
        q: str | None,
        agent_id: uuid.UUID | None,
        parent_task_id: uuid.UUID | None,
        include_subtasks: bool,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[Task], str | None]:
        query = select(Task).where(Task.user_id == user_id)
        if status != "all":
            query = query.where(Task.status.in_(_FILTERS[status]))
        if q:
            pattern = f"%{q.replace('%', r'\%').replace('_', r'\_')}%"
            query = query.where(or_(Task.title.ilike(pattern), Task.description.ilike(pattern)))
        if agent_id is not None:
            query = query.where(Task.agent_id == agent_id)
        if parent_task_id is not None:
            query = query.where(Task.parent_task_id == parent_task_id)
        elif not include_subtasks:
            query = query.where(Task.parent_task_id.is_(None))
        if cursor:
            at, tid = decode_cursor(cursor)
            query = query.where(
                or_(Task.created_at < at, and_(Task.created_at == at, Task.id < tid))
            )
        rows = list(
            (
                await self.db.execute(
                    query.order_by(Task.created_at.desc(), Task.id.desc()).limit(limit + 1)
                )
            ).scalars()
        )
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id)
        return rows, next_cursor

    async def subtasks(self, task_id: uuid.UUID) -> list[Task]:
        rows = await self.db.execute(
            select(Task).where(Task.parent_task_id == task_id).order_by(Task.created_at)
        )
        return list(rows.scalars())

    async def run_of(self, task: Task) -> AgentRun | None:
        return await self.db.get(AgentRun, task.run_id) if task.run_id else None

    async def events(
        self, user_id: uuid.UUID, task_id: uuid.UUID, *, limit: int
    ) -> list[AgentEvent]:
        task = await self.get(user_id, task_id)
        conditions = [AgentEvent.task_id == task.id]
        if task.run_id:
            conditions.append(AgentEvent.run_id == task.run_id)
        rows = await self.db.execute(
            select(AgentEvent)
            .where(AgentEvent.user_id == user_id, or_(*conditions))
            .order_by(AgentEvent.seq)
            .limit(limit)
        )
        return list(rows.scalars())

    # --- create / edit -------------------------------------------------------------------

    async def _agent_for(self, user_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
        agent = await self.db.get(Agent, agent_id)
        if agent is None or agent.user_id != user_id:
            raise NotFound("Agent not found.")
        if agent.archived_at is not None:
            raise AgentArchived()
        return agent

    async def create(self, user_id: uuid.UUID, data: TaskCreate) -> Task:
        if data.agent_id is not None:
            await self._agent_for(user_id, data.agent_id)
        task = Task(
            user_id=user_id,
            title=data.title,
            description=data.description,
            task_type=TaskType.USER.value,
            status=TaskStatus.CREATED.value,
            priority=data.priority,
            deadline=data.deadline,
            agent_id=data.agent_id,
            created_by="user",
            depends_on=[],
            extra={},
        )
        self.db.add(task)
        await self.db.flush()
        await bus.emit(
            self.db,
            user_id=user_id,
            type="task.created",
            task_id=task.id,
            agent_id=task.agent_id,
            payload={"task": task_payload(task)},
        )
        await bus.commit(self.db)
        if data.start and data.agent_id is not None:
            task, _ = await self.start(user_id, task.id)
        return task

    async def update(self, user_id: uuid.UUID, task_id: uuid.UUID, data: TaskUpdate) -> Task:
        task = await lock_task(self.db, task_id)
        if task.user_id != user_id:
            raise NotFound("Task not found.")
        if TaskStatus(task.status) not in ACTIVE_TASK:
            raise InvalidTransition("A finished task cannot be edited.")
        fields = data.model_fields_set
        if data.title is not None:
            task.title = data.title
        if data.description is not None:
            task.description = data.description
        if data.priority is not None:
            task.priority = data.priority
        if "deadline" in fields:
            task.deadline = data.deadline
        if "agent_id" in fields:
            if TaskStatus(task.status) != TaskStatus.CREATED:
                raise InvalidTransition("The agent can only be changed before the task starts.")
            if data.agent_id is not None:
                await self._agent_for(user_id, data.agent_id)
            task.agent_id = data.agent_id
        task.updated_at = datetime.now(UTC)
        await bus.emit(
            self.db,
            user_id=user_id,
            type="task.updated",
            task_id=task.id,
            agent_id=task.agent_id,
            run_id=task.run_id,
            payload={"reason": "edited", "task": task_payload(task)},
        )
        await bus.commit(self.db)
        return task

    # --- lifecycle -----------------------------------------------------------------------

    async def start(
        self,
        user_id: uuid.UUID,
        task_id: uuid.UUID,
        *,
        parent_run_id: uuid.UUID | None = None,
        conversation_id: uuid.UUID | None = None,
        enqueue: bool = True,
    ) -> tuple[Task, AgentRun]:
        """created → queued: reserve the agent, create the run, enqueue the job."""
        await ensure_engine_running(self.db, user_id)
        task = await lock_task(self.db, task_id)
        if task.user_id != user_id:
            raise NotFound("Task not found.")
        if task.agent_id is None:
            raise InvalidTransition("Assign an agent before starting the task.")
        agent = await lock_agent(self.db, task.agent_id)
        if agent.archived_at is not None:
            raise AgentArchived()
        if agent_is_busy(agent):
            raise AgentBusy()
        if AgentStatus(agent.status) in (AgentStatus.FAILED, AgentStatus.COMPLETED):
            await set_agent_status(self.db, agent, AgentStatus.IDLE, reason="new_task")

        run = AgentRun(
            user_id=user_id,
            agent_id=agent.id,
            task_id=task.id,
            status=TaskStatus.QUEUED.value,
            parent_run_id=parent_run_id,
            conversation_id=conversation_id,
            state={},
            usage={},
        )
        self.db.add(run)
        await self.db.flush()
        task.run_id = run.id
        agent.current_task_id = task.id
        if agent.agent_type == AgentType.ORCHESTRATOR.value:
            agent.run_id = run.id
        await set_task_status(self.db, task, TaskStatus.QUEUED, reason="started", run=run)
        await self.audit.record(
            "agent.run_started",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="task",
            resource_id=str(task.id),
            details={"agent_id": str(agent.id), "run_id": str(run.id)},
        )
        await bus.commit(self.db)
        if enqueue and self.queue is not None:
            await self.queue.enqueue_task(task.id)
        return task, run

    async def cancel(
        self, user_id: uuid.UUID, task_id: uuid.UUID, *, reason: str = "cancelled_by_user"
    ) -> Task:
        task = await lock_task(self.db, task_id)
        if task.user_id != user_id:
            raise NotFound("Task not found.")
        await self._cancel_tree(task, reason)
        await self.audit.record(
            "task.cancelled",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="task",
            resource_id=str(task.id),
            details={"reason": reason},
        )
        await bus.commit(self.db)
        return task

    async def _cancel_tree(self, task: Task, reason: str) -> None:
        if TaskStatus(task.status) not in ACTIVE_TASK:
            raise InvalidTransition("This task is already finished.")
        for child in await self.subtasks(task.id):
            if TaskStatus(child.status) in ACTIVE_TASK:
                await self._cancel_tree(await lock_task(self.db, child.id), "parent_cancelled")
        run = await self.run_of(task)
        await set_task_status(self.db, task, TaskStatus.CANCELLED, reason=reason, run=run)
        if task.agent_id:
            agent = await lock_agent(self.db, task.agent_id)
            if agent.current_task_id == task.id:
                await release_agent(self.db, agent, to=AgentStatus.IDLE, reason=reason)

    async def retry(self, user_id: uuid.UUID, task_id: uuid.UUID) -> Task:
        """failed/cancelled → a NEW task (attempt + 1); the old one keeps its history."""
        old = await self.get(user_id, task_id)
        if TaskStatus(old.status) not in (TaskStatus.FAILED, TaskStatus.CANCELLED):
            raise InvalidTransition("Only failed or cancelled tasks can be retried.")
        if old.parent_task_id is not None:
            raise InvalidTransition("Retry the parent task instead of a subtask.")
        task = Task(
            user_id=user_id,
            title=old.title,
            description=old.description,
            task_type=old.task_type,
            status=TaskStatus.CREATED.value,
            priority=old.priority,
            deadline=old.deadline,
            agent_id=old.agent_id,
            attempt=old.attempt + 1,
            retry_of_id=old.id,
            created_by="user",
            depends_on=[],
            extra=dict(old.extra or {}),
        )
        self.db.add(task)
        await self.db.flush()
        await bus.emit(
            self.db,
            user_id=user_id,
            type="task.created",
            task_id=task.id,
            agent_id=task.agent_id,
            payload={"task": task_payload(task), "retry_of": str(old.id)},
        )
        await bus.commit(self.db)
        if task.agent_id is not None:
            task, _ = await self.start(user_id, task.id)
        return task


async def count_tasks(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    rows = await db.execute(
        select(Task.status, func.count()).where(Task.user_id == user_id).group_by(Task.status)
    )
    return {status: n for status, n in rows.all()}
