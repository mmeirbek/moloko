from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.agents.state import ACTIVE_TASK
from app.api.deps import CurrentAuth, DbSession, QueueDep, SettingsDep
from app.events import bus
from app.models.task import Task
from app.schemas.tasks import StopAllResult, StorageStatus, SystemLimits, SystemState
from app.services.audit import AuditService
from app.services.storage import storage_status
from app.services.system import count_active_tasks, engine_stopped, set_engine_stopped
from app.services.tasks import TaskService

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/state", response_model=SystemState)
async def system_state(ctx: CurrentAuth, db: DbSession) -> SystemState:
    return SystemState(
        engine_stopped=await engine_stopped(db, ctx.user.id),
        active_tasks=await count_active_tasks(db, ctx.user.id),
    )


@router.get(
    "/limits", response_model=SystemLimits, summary="Global limits (per-agent ones may be lower)"
)
async def system_limits(ctx: CurrentAuth, settings: SettingsDep) -> SystemLimits:
    return SystemLimits(
        max_steps_per_run=settings.max_steps_per_run,
        run_timeout_seconds=settings.run_timeout_seconds,
        max_active_subagents_per_run=settings.max_active_subagents_per_run,
        max_subagent_depth=settings.max_subagent_depth,
        memory_context_max_chars=settings.memory_context_max_chars,
        memory_entry_max_chars=settings.memory_entry_max_chars,
    )


@router.get(
    "/storage", response_model=StorageStatus, summary="Backups and disk space (spec 21.2/21.3)"
)
async def system_storage(ctx: CurrentAuth, settings: SettingsDep) -> StorageStatus:
    return StorageStatus.model_validate(storage_status(settings))


@router.post(
    "/stop-all", response_model=StopAllResult, summary="Kill switch: stop every active run"
)
async def stop_all(ctx: CurrentAuth, db: DbSession, queue: QueueDep) -> StopAllResult:
    await set_engine_stopped(db, ctx.user.id, True)
    await bus.commit(db)
    roots = (
        await db.execute(
            select(Task.id).where(
                Task.user_id == ctx.user.id,
                Task.parent_task_id.is_(None),
                Task.status.in_([s.value for s in ACTIVE_TASK]),
            )
        )
    ).scalars()
    service = TaskService(db, queue)
    cancelled = 0
    for task_id in list(roots):
        await service.cancel(ctx.user.id, task_id, reason="kill_switch")
        cancelled += 1
    await AuditService(db).record(
        "system.stop_all",
        "success",
        actor_type="user",
        actor_id=ctx.user.id,
        user_id=ctx.user.id,
        details={"cancelled_tasks": cancelled},
    )
    await bus.commit(db)
    return StopAllResult(cancelled_tasks=cancelled)


@router.post(
    "/start", response_model=SystemState, summary="Allow agents to run again after stop-all"
)
async def start_engine(ctx: CurrentAuth, db: DbSession) -> SystemState:
    await set_engine_stopped(db, ctx.user.id, False)
    await AuditService(db).record(
        "system.start", "success", actor_type="user", actor_id=ctx.user.id, user_id=ctx.user.id
    )
    await bus.commit(db)
    return SystemState(engine_stopped=False, active_tasks=await count_active_tasks(db, ctx.user.id))
