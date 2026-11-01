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
from app.push.dispatcher import dispatch as dispatch_push
from app.runtimes.native import NativeRuntime
from app.sandbox.base import Sandbox
from app.sandbox.client import RunnerSandbox
from app.services.approvals import expire_due
from app.services.workspaces import clean_task_workspaces
from app.tasks.queue import TaskEnqueuer, TaskQueue
from app.workers.recovery import recover, sweep_queued

logger = logging.getLogger("moloko.worker")


def make_sandbox(settings: Settings) -> Sandbox | None:
    """The code-execution backend (spec 16), or None when it is not configured."""
    if not settings.sandbox_url or settings.sandbox_runner_token is None:
        return None
    return RunnerSandbox(settings)


def build_executor(
    db: Database,
    gateway: ModelGateway,
    settings: Settings,
    queue: TaskEnqueuer | None,
    sandbox: Sandbox | None = None,
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
        sandbox=sandbox if sandbox is not None else make_sandbox(settings),
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
    expired = await expire_due(ctx["db"].sessionmaker, ctx["queue"])
    if expired:
        logger.info("approvals_expired", extra={"count": expired})


async def push_notifications(ctx: dict[str, Any]) -> None:
    """Every few seconds: Web Push for new approvals and finished tasks."""
    sent = await dispatch_push(ctx["db"].sessionmaker, ctx["settings"])
    if sent:
        logger.info("push_sent", extra={"count": sent})


async def search_index(ctx: dict[str, Any]) -> None:
    """Every half minute: bring the search index up to date with memories and files."""
    from app.search.index import index_all

    done = await index_all(ctx["db"].sessionmaker, ctx["gateway"], ctx["settings"])
    if done:
        logger.info("search_indexed", extra={"count": done})


async def housekeeping(ctx: dict[str, Any]) -> None:
    """Hourly: delete files of old finished task workspaces (spec 16)."""
    async with ctx["db"].sessionmaker() as db:
        cleaned = await clean_task_workspaces(db, ctx["settings"])
        await db.commit()
    if cleaned:
        logger.info("workspaces_cleaned", extra={"count": cleaned})
