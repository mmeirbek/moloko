"""Global kill switch (spec 7.2): stop all active runs and refuse new ones until restarted."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import ACTIVE_TASK
from app.core.errors import Conflict
from app.models.system import SystemSetting
from app.models.task import Task

ENGINE_KEY = "engine"


class EngineStopped(Conflict):
    code = "engine_stopped"
    message = "All agents are stopped (kill switch). Start the engine again in Settings."


async def engine_stopped(db: AsyncSession, user_id: uuid.UUID) -> bool:
    row = (
        await db.execute(
            select(SystemSetting).where(
                SystemSetting.user_id == user_id, SystemSetting.key == ENGINE_KEY
            )
        )
    ).scalar_one_or_none()
    return bool(row and row.value.get("stopped"))


async def set_engine_stopped(db: AsyncSession, user_id: uuid.UUID, stopped: bool) -> None:
    row = (
        await db.execute(
            select(SystemSetting)
            .where(SystemSetting.user_id == user_id, SystemSetting.key == ENGINE_KEY)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(SystemSetting(user_id=user_id, key=ENGINE_KEY, value={"stopped": stopped}))
    else:
        row.value = {"stopped": stopped}


async def ensure_engine_running(db: AsyncSession, user_id: uuid.UUID) -> None:
    if await engine_stopped(db, user_id):
        raise EngineStopped()


async def count_active_tasks(db: AsyncSession, user_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(Task)
        .where(Task.user_id == user_id, Task.status.in_([s.value for s in ACTIVE_TASK]))
    )
    return int(result.scalar_one())
