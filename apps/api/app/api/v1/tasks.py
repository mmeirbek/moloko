from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, Query, Response, status

from app.api.deps import CurrentAuth, DbSession, QueueDep, SettingsDep
from app.models.event import AgentEvent
from app.schemas.common import Page
from app.schemas.tasks import (
    EventOut,
    RunOut,
    TaskCreate,
    TaskDetail,
    TaskFilter,
    TaskOut,
    TaskUpdate,
)
from app.services.idempotency import idempotent
from app.services.tasks import TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])


def event_out(e: AgentEvent) -> EventOut:
    return EventOut(
        id=e.id,
        seq=e.seq,
        type=e.type,
        version=e.version,
        timestamp=e.created_at,
        agent_id=e.agent_id,
        task_id=e.task_id,
        run_id=e.run_id,
        payload=e.payload,
    )


@router.get("", response_model=Page[TaskOut])
async def list_tasks(
    ctx: CurrentAuth,
    db: DbSession,
    queue: QueueDep,
    status_filter: TaskFilter = Query("all", alias="status"),  # noqa: B008
    q: str | None = Query(None, max_length=200),
    agent_id: uuid.UUID | None = None,
    parent_task_id: uuid.UUID | None = None,
    include_subtasks: bool = False,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
) -> Page[TaskOut]:
    rows, next_cursor = await TaskService(db, queue).list_tasks(
        ctx.user.id,
        status=status_filter,
        q=q,
        agent_id=agent_id,
        parent_task_id=parent_task_id,
        include_subtasks=include_subtasks,
        limit=limit,
        cursor=cursor,
    )
    return Page(items=[TaskOut.model_validate(t) for t in rows], next_cursor=next_cursor)


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(
    body: TaskCreate,
    ctx: CurrentAuth,
    db: DbSession,
    queue: QueueDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TaskOut:
    async def action() -> TaskOut:
        return TaskOut.model_validate(await TaskService(db, queue).create(ctx.user.id, body))

    return await idempotent(
        db,
        user_id=ctx.user.id,
        scope="POST /tasks",
        key=idempotency_key,
        body=body.model_dump(mode="json"),
        model=TaskOut,
        action=action,
    )


@router.get("/{task_id}", response_model=TaskDetail)
async def get_task(
    task_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, queue: QueueDep
) -> TaskDetail:
    service = TaskService(db, queue)
    task = await service.get(ctx.user.id, task_id)
    run = await service.run_of(task)
    return TaskDetail(
        task=TaskOut.model_validate(task),
        subtasks=[TaskOut.model_validate(t) for t in await service.subtasks(task.id)],
        run=RunOut.model_validate(run) if run else None,
    )


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: uuid.UUID, body: TaskUpdate, ctx: CurrentAuth, db: DbSession, queue: QueueDep
) -> TaskOut:
    return TaskOut.model_validate(await TaskService(db, queue).update(ctx.user.id, task_id, body))


@router.post("/{task_id}/cancel", response_model=TaskOut)
async def cancel_task(
    task_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, queue: QueueDep
) -> TaskOut:
    return TaskOut.model_validate(await TaskService(db, queue).cancel(ctx.user.id, task_id))


@router.post("/{task_id}/retry", response_model=TaskOut, summary="Retry as a new attempt")
async def retry_task(
    task_id: uuid.UUID,
    ctx: CurrentAuth,
    db: DbSession,
    queue: QueueDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TaskOut:
    async def action() -> TaskOut:
        return TaskOut.model_validate(await TaskService(db, queue).retry(ctx.user.id, task_id))

    return await idempotent(
        db,
        user_id=ctx.user.id,
        scope=f"POST /tasks/{task_id}/retry",
        key=idempotency_key,
        body={},
        model=TaskOut,
        action=action,
    )


@router.get("/{task_id}/events", response_model=list[EventOut], summary="Execution history")
async def task_events(
    task_id: uuid.UUID,
    ctx: CurrentAuth,
    db: DbSession,
    queue: QueueDep,
    limit: int = Query(500, ge=1, le=2000),
) -> list[EventOut]:
    return [
        event_out(e) for e in await TaskService(db, queue).events(ctx.user.id, task_id, limit=limit)
    ]


@router.get(
    "/{task_id}/export.md",
    response_class=Response,
    responses={200: {"content": {"text/markdown": {}}}},
    summary="The task and its result as a Markdown file",
)
async def export_markdown(
    task_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, queue: QueueDep
) -> Response:
    from urllib.parse import quote

    from app.services.export import safe_name, task_markdown

    task = await TaskService(db, queue).get(ctx.user.id, task_id)
    return Response(
        content=task_markdown(task).encode(),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(safe_name(task.title))}.md"
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/{task_id}/export.pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
    summary="Print the task's result to PDF (sandbox browser, no network)",
)
async def export_pdf(
    task_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, queue: QueueDep, settings: SettingsDep
) -> Response:
    from urllib.parse import quote

    from app.services.export import task_pdf
    from app.workers import jobs

    task = await TaskService(db, queue).get(ctx.user.id, task_id)
    name, data = await task_pdf(db, settings, jobs.make_sandbox(settings), task)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
