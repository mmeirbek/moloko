"""Approval decisions (spec 15.4): approve / reject / cancel the task; expiry.

An approval belongs to ONE operation (tool + hash of the exact arguments). Approving opens
a fresh ``APPROVAL_TTL_MINUTES`` window to execute it; the tool runner checks the status,
hash, use and expiry again before it runs anything.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.engine import lock_task, set_task_status
from app.agents.state import TaskStatus
from app.core.config import Settings
from app.core.errors import Conflict, NotFound
from app.events import bus
from app.models.agent import Agent
from app.models.task import Task
from app.models.tooling import Approval
from app.services.audit import AuditService
from app.tasks.queue import TaskEnqueuer
from app.tools.runner import approval_payload


class ApprovalNotPending(Conflict):
    code = "approval_not_pending"
    message = "This request was already answered or has expired."


async def _agent_names(db: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = await db.execute(select(Agent.id, Agent.name).where(Agent.id.in_(ids)))
    return {r.id: r.name for r in rows}


async def payloads(db: AsyncSession, approvals: list[Approval]) -> list[dict[str, Any]]:
    names = await _agent_names(db, {a.agent_id for a in approvals})
    return [approval_payload(a, names.get(a.agent_id)) for a in approvals]


async def pending_for_user(db: AsyncSession, user_id: uuid.UUID) -> list[Approval]:
    rows = await db.execute(
        select(Approval)
        .where(Approval.user_id == user_id, Approval.status == "pending")
        .order_by(Approval.created_at)
    )
    return list(rows.scalars())


async def _resolve(
    db: AsyncSession,
    approval: Approval,
    status: str,
    *,
    actor: Literal["user", "system"],
    requeue: bool,
) -> Task | None:
    """Set the final status, emit ``approval.resolved`` and (optionally) re-queue the task."""
    now = datetime.now(UTC)
    approval.status, approval.resolved_at = status, now
    task = await lock_task(db, approval.task_id)
    if requeue and TaskStatus(task.status) == TaskStatus.WAITING_APPROVAL:
        await set_task_status(db, task, TaskStatus.QUEUED, reason=f"approval_{status}")
    names = await _agent_names(db, {approval.agent_id})
    await bus.emit(
        db,
        user_id=approval.user_id,
        type="approval.resolved",
        agent_id=approval.agent_id,
        task_id=approval.task_id,
        run_id=approval.run_id,
        payload={"approval": approval_payload(approval, names.get(approval.agent_id))},
    )
    await AuditService(db).record(
        f"approval.{status}",
        "success",
        actor_type=actor,
        actor_id=approval.user_id if actor == "user" else None,
        user_id=approval.user_id,
        resource_type="approval",
        resource_id=str(approval.id),
        details={
            "tool": approval.tool_name,
            "args_hash": approval.args_hash,
            "task_id": str(approval.task_id),
        },
    )
    return task if requeue and TaskStatus(task.status) == TaskStatus.QUEUED else None


async def cancel_pending_for_task(db: AsyncSession, task_id: uuid.UUID) -> None:
    """The task was cancelled: its open approval requests can never be used."""
    rows = await db.execute(
        select(Approval)
        .where(Approval.task_id == task_id, Approval.status == "pending")
        .with_for_update()
    )
    for approval in rows.scalars():
        await _resolve(db, approval, "cancelled", actor="user", requeue=False)


class ApprovalService:
    def __init__(self, db: AsyncSession, settings: Settings, queue: TaskEnqueuer | None) -> None:
        self.db, self.settings, self.queue = db, settings, queue

    async def get(
        self, user_id: uuid.UUID, approval_id: uuid.UUID, *, lock: bool = False
    ) -> Approval:
        approval = await self.db.get(Approval, approval_id, with_for_update=lock)
        if approval is None or approval.user_id != user_id:
            raise NotFound("Approval request not found.")
        return approval

    async def list_approvals(
        self, user_id: uuid.UUID, *, status: str | None, task_id: uuid.UUID | None, limit: int
    ) -> list[Approval]:
        query = select(Approval).where(Approval.user_id == user_id)
        if status:
            query = query.where(Approval.status == status)
        if task_id:
            query = query.where(Approval.task_id == task_id)
        rows = await self.db.execute(query.order_by(Approval.created_at.desc()).limit(limit))
        return list(rows.scalars())

    async def decide(self, user_id: uuid.UUID, approval_id: uuid.UUID, approve: bool) -> Approval:
        approval = await self.get(user_id, approval_id, lock=True)
        now = datetime.now(UTC)
        if approval.status == "pending" and approval.expires_at <= now:
            task = await _resolve(self.db, approval, "expired", actor="system", requeue=True)
            await bus.commit(self.db)
            await self._enqueue(task)
            raise ApprovalNotPending("This request expired before it was answered.")
        if approval.status != "pending":
            raise ApprovalNotPending()
        if approve:
            # A fresh window to execute exactly this operation.
            approval.expires_at = now + timedelta(minutes=self.settings.approval_ttl_minutes)
        task = await _resolve(
            self.db, approval, "approved" if approve else "rejected", actor="user", requeue=True
        )
        await bus.commit(self.db)
        await self._enqueue(task)
        return approval

    async def cancel_task(self, user_id: uuid.UUID, approval_id: uuid.UUID) -> Approval:
        from app.services.tasks import TaskService  # tasks → approvals at import time
        from app.services.workspaces import root_task

        approval = await self.get(user_id, approval_id)
        if approval.status != "pending":
            raise ApprovalNotPending()
        task = await self.db.get(Task, approval.task_id)
        assert task is not None
        root = await root_task(self.db, task)
        await TaskService(self.db, self.queue).cancel(
            user_id, root.id, reason="cancelled_at_approval"
        )
        await self.db.refresh(approval)
        return approval

    async def _enqueue(self, task: Task | None) -> None:
        if task is not None and self.queue is not None:
            await self.queue.enqueue_task(task.id)


async def expire_due(
    sessionmaker: async_sessionmaker[AsyncSession], queue: TaskEnqueuer | None
) -> int:
    """Worker sweeper: unanswered requests past their expiry → ``expired``; the agent
    continues and is told the action was not approved."""
    now = datetime.now(UTC)
    async with sessionmaker() as db:
        ids = list(
            (
                await db.execute(
                    select(Approval.id).where(
                        Approval.status == "pending", Approval.expires_at <= now
                    )
                )
            ).scalars()
        )
    count = 0
    for approval_id in ids:
        async with sessionmaker() as db:
            approval = await db.get(Approval, approval_id, with_for_update=True)
            if approval is None or approval.status != "pending":
                continue
            task = await _resolve(db, approval, "expired", actor="system", requeue=True)
            await bus.commit(db)
            if task is not None and queue is not None:
                await queue.enqueue_task(task.id)
            count += 1
    return count
