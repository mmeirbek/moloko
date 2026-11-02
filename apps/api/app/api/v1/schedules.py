from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, Response, status

from app.api.deps import CurrentAuth, DbSession, QueueDep, SettingsDep
from app.schemas.schedules import (
    ScheduleCreate,
    ScheduleList,
    ScheduleOut,
    SchedulePreview,
    SchedulePreviewIn,
    ScheduleStarted,
    ScheduleUpdate,
)
from app.schemas.tasks import RunOut, TaskOut
from app.services.idempotency import idempotent
from app.services.schedules import ScheduleService

router = APIRouter(prefix="/schedules", tags=["schedules"])


@router.get("", response_model=ScheduleList, summary="Scheduled tasks (oldest first)")
async def list_schedules(ctx: CurrentAuth, db: DbSession, settings: SettingsDep) -> ScheduleList:
    items = await ScheduleService(db, settings).list_schedules(ctx.user.id)
    return ScheduleList(
        items=items,
        max_schedules=settings.schedules_max_per_user,
        min_interval_minutes=settings.schedule_min_interval_minutes,
    )


@router.post(
    "",
    response_model=ScheduleOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a scheduled task (next_run_at is computed)",
)
async def create_schedule(
    body: ScheduleCreate, ctx: CurrentAuth, db: DbSession, settings: SettingsDep
) -> ScheduleOut:
    return await ScheduleService(db, settings).create(ctx.user.id, body)


@router.post(
    "/preview",
    response_model=SchedulePreview,
    summary="The next runs of a rule, without saving anything",
)
async def preview_schedule(
    body: SchedulePreviewIn, ctx: CurrentAuth, db: DbSession, settings: SettingsDep
) -> SchedulePreview:
    return SchedulePreview(next_runs=ScheduleService(db, settings).preview(body))


@router.get("/{schedule_id}", response_model=ScheduleOut)
async def get_schedule(
    schedule_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, settings: SettingsDep
) -> ScheduleOut:
    service = ScheduleService(db, settings)
    return await service.out(await service.get(ctx.user.id, schedule_id))


@router.patch("/{schedule_id}", response_model=ScheduleOut)
async def update_schedule(
    schedule_id: uuid.UUID,
    body: ScheduleUpdate,
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
) -> ScheduleOut:
    return await ScheduleService(db, settings).update(ctx.user.id, schedule_id, body)


@router.delete(
    "/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete the schedule (tasks it started stay)",
)
async def delete_schedule(
    schedule_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, settings: SettingsDep
) -> Response:
    await ScheduleService(db, settings).delete(ctx.user.id, schedule_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{schedule_id}/run-now",
    response_model=ScheduleStarted,
    summary="Start the scheduled task now (the plan stays as it is)",
)
async def run_schedule_now(
    schedule_id: uuid.UUID,
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    queue: QueueDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ScheduleStarted:
    async def action() -> ScheduleStarted:
        schedule, task, run = await ScheduleService(db, settings, queue).run_now(
            ctx.user.id, schedule_id
        )
        return ScheduleStarted(
            schedule=schedule, task=TaskOut.model_validate(task), run=RunOut.model_validate(run)
        )

    return await idempotent(
        db,
        user_id=ctx.user.id,
        scope=f"POST /schedules/{schedule_id}/run-now",
        key=idempotency_key,
        body={},
        model=ScheduleStarted,
        action=action,
    )
