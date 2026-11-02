"""Task Manager (spec 9): create, assign, start, cancel, retry, history."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.engine import (
    agent_is_busy,
    agent_payload,
    lock_agent,
    lock_run,
    lock_task,
    release_agent,
    set_agent_status,
    set_task_status,
    task_payload,
)
from app.agents.state import (
    ACTIVE_TASK,
    TERMINAL_TASK,
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
from app.services.approvals import cancel_pending_for_task
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
        run = await prepare_start(
            self.db, task, parent_run_id=parent_run_id, conversation_id=conversation_id
        )
        await self.audit.record(
            "agent.run_started",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="task",
            resource_id=str(task.id),
            details={"agent_id": str(task.agent_id), "run_id": str(run.id)},
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
        await after_cancel(self.db, self.queue, user_id)
        return task

    async def _cancel_tree(self, task: Task, reason: str) -> None:
        if TaskStatus(task.status) not in ACTIVE_TASK:
            raise InvalidTransition("This task is already finished.")
        for child in await self.subtasks(task.id):
            if TaskStatus(child.status) in ACTIVE_TASK:
                await self._cancel_tree(await lock_task(self.db, child.id), "parent_cancelled")
        run = await self.run_of(task)
        await set_task_status(self.db, task, TaskStatus.CANCELLED, reason=reason, run=run)
        await cancel_pending_for_task(self.db, task.id)
        if task.agent_id:
            agent = await lock_agent(self.db, task.agent_id)
            if agent.current_task_id == task.id:
                await release_agent(self.db, agent, to=AgentStatus.IDLE, reason=reason)
            if (
                task.parent_task_id is None
                and agent.agent_type == AgentType.ORCHESTRATOR.value
                and run
            ):
                await archive_subagents(self.db, run.id)

    async def retry(self, user_id: uuid.UUID, task_id: uuid.UUID, *, start: bool = True) -> Task:
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
            # "Start over" works from scratch: a fresh workspace, not the stopped attempt's.
            extra={
                k: v
                for k, v in (old.extra or {}).items()
                if k not in ("continued_from", "workspace_task_id")
            },
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
        if task.agent_id is not None and start:
            task, _ = await self.start(user_id, task.id)
        return task

    async def continue_from_stop(
        self, user_id: uuid.UUID, task_id: uuid.UUID, instruction: str | None = None
    ) -> Task:
        """failed/cancelled → a NEW attempt that starts from the old run's saved progress
        (its conversation with the model, tool results included) instead of from scratch.
        Steps already done are not repeated; the agent is told why it stopped."""
        from app.runtimes.native import continuation_messages  # runtime → tasks at import time

        old = await self.get(user_id, task_id)
        if TaskStatus(old.status) not in (TaskStatus.FAILED, TaskStatus.CANCELLED):
            raise InvalidTransition("Only failed or cancelled tasks can be continued.")
        if old.parent_task_id is not None:
            raise InvalidTransition("Continue the parent task instead of a subtask.")
        old_run = await self.db.get(AgentRun, old.run_id) if old.run_id else None
        saved = (old_run.state or {}).get("messages") if old_run else None
        if old_run is None or not saved or old.agent_id is None:  # nothing saved: a plain retry
            return await self.retry(user_id, task_id)
        task = await self.retry(user_id, task_id, start=False)
        task.extra = {
            **(task.extra or {}),
            "continued_from": str(old.id),
            # the files are part of where it stopped: keep working in the same folder
            "workspace_task_id": str((old.extra or {}).get("workspace_task_id") or old.id),
        }
        task, run = await self.start(user_id, task.id, enqueue=False)
        run.state = {
            **(run.state or {}),
            "messages": continuation_messages(
                saved,
                old.status,
                old.error_code,
                old.error_message,
                instruction,
                [str(m["text"]) for m in old_run.state.get("owner_inbox", [])],
            ),
            "continued_from_run": str(old_run.id),
        }
        await self.audit.record(
            "task.continued",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="task",
            resource_id=str(task.id),
            details={"from_task": str(old.id), "with_instruction": bool(instruction)},
        )
        await bus.commit(self.db)
        if self.queue is not None:
            await self.queue.enqueue_task(task.id)
        return task

    async def message_agent(self, user_id: uuid.UUID, task_id: uuid.UUID, text: str) -> Task:
        """The owner writes to the agent while it works: the note waits in the run and the
        agent reads it before its next step (also after a pause or an approval)."""
        task = await lock_task(self.db, task_id)
        if task.user_id != user_id:
            raise NotFound("Task not found.")
        if TaskStatus(task.status) in TERMINAL_TASK:
            raise InvalidTransition("The task has finished — continue it instead.")
        if task.run_id is None:
            raise InvalidTransition("The task has not started yet — edit its description instead.")
        agent = await self.db.get(Agent, task.agent_id) if task.agent_id else None
        if agent is None or agent.agent_type == AgentType.ORCHESTRATOR.value:
            raise InvalidTransition(
                "The Orchestrator works through its plan — write to the agent doing the step."
            )
        if not text.strip():
            raise InvalidTransition("The message is empty.")
        run = await lock_run(self.db, task.run_id)
        inbox = list((run.state or {}).get("owner_inbox", []))
        inbox.append({"text": text, "at": datetime.now(UTC).isoformat()})
        run.state = {**(run.state or {}), "owner_inbox": inbox}
        await bus.emit(
            self.db,
            user_id=user_id,
            type="task.owner_message",
            task_id=task.id,
            agent_id=task.agent_id,
            run_id=run.id,
            payload={"text": text, "delivered": False},
        )
        await bus.commit(self.db)
        return task


async def after_cancel(db: AsyncSession, queue: TaskEnqueuer | None, user_id: uuid.UUID) -> None:
    """Questions between agents (agent_ask): a cancelled question answers its asker with an
    error, a cancelled asker frees the agents it asked — now, not at the next sweep."""
    from app.agents.team import after_change  # team → tasks at import time

    await after_change(db, queue, user_id)


async def archive_subagents(db: AsyncSession, root_run_id: uuid.UUID) -> None:
    """A finished run's subagents leave the office; their history stays."""
    rows = await db.execute(
        select(Agent).where(
            Agent.run_id == root_run_id,
            Agent.agent_type == AgentType.SUBAGENT.value,
            Agent.archived_at.is_(None),
        )
    )
    now = datetime.now(UTC)
    for sub in rows.scalars():
        sub.archived_at = now
        await bus.emit(
            db,
            user_id=sub.user_id,
            type="agent.updated",
            agent_id=sub.id,
            run_id=root_run_id,
            payload={"changed": ["archived_at"], "agent": agent_payload(sub)},
        )


async def prepare_start(
    db: AsyncSession,
    task: Task,
    *,
    parent_run_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
) -> AgentRun:
    """Inside the caller's transaction (task row locked): reserve the agent, create the
    run, move the task to ``queued``. The caller commits and then enqueues."""
    if task.agent_id is None:
        raise InvalidTransition("Assign an agent before starting the task.")
    agent = await lock_agent(db, task.agent_id)
    if agent.archived_at is not None:
        raise AgentArchived()
    if agent_is_busy(agent):
        raise AgentBusy()
    if agent.agent_type != AgentType.SUBAGENT.value and AgentStatus(agent.status) in (
        AgentStatus.FAILED,
        AgentStatus.COMPLETED,
    ):
        await set_agent_status(db, agent, AgentStatus.IDLE, reason="new_task")
    run = AgentRun(
        user_id=task.user_id,
        agent_id=agent.id,
        task_id=task.id,
        status=TaskStatus.QUEUED.value,
        parent_run_id=parent_run_id,
        conversation_id=conversation_id,
        state={},
        usage={},
    )
    db.add(run)
    await db.flush()
    task.run_id = run.id
    agent.current_task_id = task.id
    if agent.agent_type == AgentType.ORCHESTRATOR.value:
        agent.run_id = run.id  # the root run of everything this orchestrator delegates
    # Reserved but still idle until a worker picks the run up: clients must see it as busy now,
    # or a second "Start" in that window is refused with "agent busy".
    await bus.emit(
        db,
        user_id=agent.user_id,
        type="agent.updated",
        agent_id=agent.id,
        task_id=task.id,
        run_id=run.id,
        payload={"changed": ["current_task_id"], "agent": agent_payload(agent)},
    )
    await set_task_status(db, task, TaskStatus.QUEUED, reason="started", run=run)
    return run
