"""End-to-end through a real ARQ worker and Redis: API enqueues, worker runs the agent."""

from __future__ import annotations

import uuid

from arq import func
from arq.worker import Worker
from fastapi import FastAPI

from app.models import Task, User
from app.tasks.queue import RUN_TASK_JOB, TaskQueue, redis_settings
from app.workers.jobs import run_task
from tests.conftest import (
    TEST_REDIS_URL,
    add_mock_model,
    create_agent,
    executor_for,
    logged_in_client,
    run_agent,
)


async def test_arq_worker_executes_enqueued_task(app: FastAPI, owner: User) -> None:
    queue = TaskQueue(TEST_REDIS_URL)
    app.state.queue = queue
    redis = await queue._pool_or_none()
    assert redis is not None
    await redis.flushdb()
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        agent = await create_agent(client)
        task_id = (await run_agent(client, agent["id"], "Via ARQ")).json()["task"]["id"]

    worker = Worker(
        functions=[func(run_task, name=RUN_TASK_JOB)],
        redis_settings=redis_settings(TEST_REDIS_URL),
        burst=True,
        ctx={"executor": executor_for(app)},
        handle_signals=False,
        poll_delay=0.05,
    )
    await worker.main()
    await worker.close()
    await queue.close()

    async with app.state.db.sessionmaker() as db:
        task = await db.get(Task, uuid.UUID(task_id))
    assert task is not None and task.status == "completed"
    assert worker.jobs_complete == 1
