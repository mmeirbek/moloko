"""ARQ worker: executes agent runs in the background, independent of any browser.

arq app.workers.main.WorkerSettings
"""

from __future__ import annotations

from typing import Any, ClassVar

from arq import cron, func

from app.core.config import get_settings
from app.tasks.queue import RUN_TASK_JOB, redis_settings
from app.workers.jobs import housekeeping, run_task, shutdown, startup, sweep

settings = get_settings()


async def _startup(ctx: dict[str, Any]) -> None:
    ctx["settings"] = settings
    await startup(ctx)


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        func(run_task, name=RUN_TASK_JOB, timeout=settings.run_timeout_seconds + 120, max_tries=1)
    ]
    cron_jobs: ClassVar[list[Any]] = [
        cron(sweep, second={0, 30}, run_at_startup=False, unique=True),
        cron(housekeeping, minute={17}, second={0}, run_at_startup=False, unique=True),
    ]
    on_startup = _startup
    on_shutdown = shutdown
    redis_settings = redis_settings(settings.redis_url)
    max_jobs = settings.worker_max_jobs
    job_timeout = settings.run_timeout_seconds + 120
    max_tries = 1
    keep_result = 60
    health_check_interval = 30
    allow_abort_jobs = True
