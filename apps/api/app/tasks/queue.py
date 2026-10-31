"""ARQ job queue. Redis holds only the *signal* that work exists; the task itself is
in PostgreSQL. Duplicate or lost enqueues are harmless: the job atomically claims a
``queued`` task and the worker's sweeper re-enqueues queued tasks that were missed."""

from __future__ import annotations

import logging
import uuid
from typing import Protocol

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

logger = logging.getLogger("moloko.queue")

RUN_TASK_JOB = "run_task"


class TaskEnqueuer(Protocol):
    async def enqueue_task(self, task_id: uuid.UUID) -> bool: ...


def redis_settings(url: str) -> RedisSettings:
    return RedisSettings.from_dsn(url)


class TaskQueue:
    def __init__(self, redis_url: str) -> None:
        self._settings = redis_settings(redis_url)
        self._settings.conn_retries = 0
        self._pool: ArqRedis | None = None

    async def _pool_or_none(self) -> ArqRedis | None:
        if self._pool is None:
            try:
                self._pool = await create_pool(self._settings)
            except Exception as exc:  # noqa: BLE001 — the sweeper will enqueue it later
                logger.warning("queue_unavailable", extra={"error": type(exc).__name__})
                return None
        return self._pool

    async def enqueue_task(self, task_id: uuid.UUID) -> bool:
        pool = await self._pool_or_none()
        if pool is None:
            return False
        try:
            await pool.enqueue_job(
                RUN_TASK_JOB, str(task_id), _job_id=f"task:{task_id}:{uuid.uuid4().hex[:12]}"
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "enqueue_failed", extra={"task_id": str(task_id), "error": type(exc).__name__}
            )
            self._pool = None
            return False

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None
