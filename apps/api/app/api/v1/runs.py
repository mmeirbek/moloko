from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, Query

from app.api.deps import CurrentAuth, DbSession, QueueDep
from app.core.errors import NotFound
from app.models.task import Task
from app.orchestrator.service import (
    get_run,
    list_orchestrated_runs,
    run_tree,
    start_orchestrated_run,
)
from app.schemas.agents import AgentOut, StartedRun
from app.schemas.tasks import AgentMessageOut, RunCreate, RunOut, RunTree, TaskOut
from app.services.idempotency import idempotent

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=list[RunOut], summary="Orchestrated runs (Subagent Office)")
async def list_runs(
    ctx: CurrentAuth,
    db: DbSession,
    active: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
) -> list[RunOut]:
    rows = await list_orchestrated_runs(db, ctx.user.id, active_only=active, limit=limit)
    return [RunOut.model_validate(r) for r in rows]


@router.post("", response_model=StartedRun, summary="Give a task to the Orchestrator")
async def create_run(
    body: RunCreate,
    ctx: CurrentAuth,
    db: DbSession,
    queue: QueueDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> StartedRun:
    async def action() -> StartedRun:
        task, run = await start_orchestrated_run(
            db, queue, ctx.user.id, title=body.title, description=body.description
        )
        return StartedRun(task=TaskOut.model_validate(task), run=RunOut.model_validate(run))

    return await idempotent(
        db,
        user_id=ctx.user.id,
        scope="POST /runs",
        key=idempotency_key,
        body=body.model_dump(mode="json"),
        model=StartedRun,
        action=action,
    )


@router.get("/{run_id}", response_model=RunTree, summary="Plan, subagents, subtasks and messages")
async def get_run_tree(run_id: uuid.UUID, ctx: CurrentAuth, db: DbSession) -> RunTree:
    run = await get_run(db, ctx.user.id, run_id)
    task = await db.get(Task, run.task_id)
    if task is None:
        raise NotFound("Run task not found.")
    agents, tasks, messages = await run_tree(db, run)
    return RunTree(
        run=RunOut.model_validate(run),
        task=TaskOut.model_validate(task),
        subagents=[AgentOut.model_validate(a).model_dump(mode="json") for a in agents],
        subtasks=[TaskOut.model_validate(t) for t in tasks],
        messages=[AgentMessageOut.model_validate(m) for m in messages],
    )
