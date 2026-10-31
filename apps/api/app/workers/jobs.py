"""ARQ job functions (importable without environment configuration)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.agents.executor import Executor
from app.core.config import Settings
from app.core.db import Database
from app.core.logging import configure_logging
from app.core.redis import create_redis
from app.events.bus import EventPublisher, set_publisher
from app.orchestrator import mock_script  # noqa: F401 — registers offline mock replies
from app.orchestrator.runtime import OrchestratorRuntime, SubagentRuntime
from app.orchestrator.scheduler import after_task as scheduler_after_task
from app.providers.gateway import ModelGateway
from app.runtimes.native import NativeRuntime
from app.tasks.queue import TaskEnqueuer, TaskQueue
from app.workers.recovery import recover, sweep_queued

logger = logging.getLogger("moloko.worker")


def build_executor(
    db: Database, gateway: ModelGateway, settings: Settings, queue: TaskEnqueuer | None
) -> Executor:
    """Executor with every runtime this server supports."""
    return Executor(
        db.sessionmaker,
        gateway,
        settings,
        runtimes={
            "native": NativeRuntime(),
            "subagent": SubagentRuntime(),
            "orchestrator": OrchestratorRuntime(),
        },
        after_task=lambda task_id: scheduler_after_task(db.sessionmaker, task_id, queue),
    )


async def startup(ctx: dict[str, Any]) -> None:
    settings: Settings = ctx["settings"]
    configure_logging(settings.log_level)
    db = Database(settings)
    redis = create_redis(settings.redis_url)
    set_publisher(EventPublisher(redis))
    queue = TaskQueue(settings.redis_url)
    gateway = ModelGateway(settings)
    ctx.update(
        db=db,
        redis=redis,
        queue=queue,
        gateway=gateway,
        executor=build_executor(db, gateway, settings, queue),
    )
    await recover(db.sessionmaker, queue)
    logger.info("worker_started")


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["queue"].close()
    await ctx["redis"].aclose()
    await ctx["db"].dispose()
    set_publisher(None)
    logger.info("worker_stopped")


async def run_task(ctx: dict[str, Any], task_id: str) -> None:
    await ctx["executor"].execute(uuid.UUID(task_id))


async def sweep(ctx: dict[str, Any]) -> None:
    settings: Settings = ctx["settings"]
    count = await sweep_queued(
        ctx["db"].sessionmaker, ctx["queue"], settings.worker_requeue_after_seconds
    )
    if count:
        logger.info("requeued_stale_tasks", extra={"count": count})
