"""Test fixtures.

Integration tests run against a real PostgreSQL and Redis (spec section 23).
Point them at throwaway instances with TEST_DATABASE_URL / TEST_REDIS_URL;
``infrastructure/scripts/test-api.sh`` starts suitable containers.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.main import create_app

# Register the scripted orchestrator replies before any test monkeypatches the handler list.
from app.orchestrator import mock_script as _mock_script  # noqa: F401
from app.services.users import UserService

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://moloko:moloko@127.0.0.1:55432/moloko_test"
)
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:56379/15")
API_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OWNER_USERNAME = "owner"
OWNER_PASSWORD = "correct horse battery staple"


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": TEST_DATABASE_URL,
        "redis_url": TEST_REDIS_URL,
        "secret_key": "test-secret-key-" + "x" * 32,
        "environment": "test",
        "log_level": "WARNING",
        "cookie_secure": True,
        "app_encryption_key": "test-encryption-key-" + "e" * 32,
        "enable_mock_provider": True,
        "provider_retry_base_delay_seconds": 0.0,
        "worker_control_poll_seconds": 0.05,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def alembic_config(database_url: str) -> Config:
    cfg = Config(os.path.join(API_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(API_ROOT, "migrations"))
    cfg.attributes["database_url"] = database_url
    cfg.attributes["configure_logger"] = False
    return cfg


async def run_alembic(database_url: str, fn: Callable[..., None], *args: Any) -> None:
    # env.py calls asyncio.run(); run it in a worker thread that has no event loop.
    await asyncio.to_thread(fn, alembic_config(database_url), *args)


@pytest.fixture(scope="session", autouse=True)
async def migrated_database() -> AsyncIterator[None]:
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()
    await run_alembic(TEST_DATABASE_URL, command.upgrade, "head")
    yield


TABLES = (
    "search_chunks",
    "usage_records",
    "push_subscriptions",
    "attachments",
    "approvals",
    "tool_calls",
    "workspace_files",
    "workspaces",
    "tools",
    "mcp_servers",
    "integrations",
    "memory_revisions",
    "memories",
    "agent_messages",
    "agent_events",
    "idempotency_keys",
    "system_settings",
    "tasks",
    "agent_runs",
    "agents",
    "messages",
    "conversations",
    "model_configs",
    "model_providers",
    "sessions",
    "users",
    "audit_logs",
)


@pytest.fixture(autouse=True)
async def clean_tables(migrated_database: None) -> AsyncIterator[None]:
    yield
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        # TRUNCATE bypasses the row-level append-only trigger on audit_logs.
        await conn.execute(text("TRUNCATE " + ", ".join(TABLES) + " CASCADE"))
    await engine.dispose()


AppFactory = Callable[..., Awaitable[FastAPI]]


@pytest.fixture
async def app_factory() -> AsyncIterator[AppFactory]:
    async with AsyncExitStack() as stack:

        async def factory(**overrides: Any) -> FastAPI:
            app = create_app(make_settings(**overrides))
            await stack.enter_async_context(app.router.lifespan_context(app))
            return app

        yield factory


@pytest.fixture
async def app(app_factory: AppFactory) -> FastAPI:
    return await app_factory()


def make_client(app: FastAPI, *, raise_app_exceptions: bool = True) -> httpx.AsyncClient:
    # https so that Secure cookies are sent back, exactly like behind Tailscale Serve.
    # Starlette re-raises unhandled errors after sending the 500/503 response (so the
    # server logs them); tests of that response pass raise_app_exceptions=False.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
    return httpx.AsyncClient(transport=transport, base_url="https://testserver")


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client(app) as c:
        yield c


@pytest.fixture
async def owner(app: FastAPI) -> Any:
    async with app.state.db.sessionmaker() as session:
        return await UserService(session).create_owner(OWNER_USERNAME, OWNER_PASSWORD, "Owner")


async def csrf_headers(client: httpx.AsyncClient) -> dict[str, str]:
    token = client.cookies.get("moloko_csrf")
    if token is None:
        resp = await client.get("/api/v1/auth/csrf")
        assert resp.status_code == 200
        token = client.cookies.get("moloko_csrf")
    assert token
    return {"X-CSRF-Token": token}


async def login(
    client: httpx.AsyncClient, username: str = OWNER_USERNAME, password: str = OWNER_PASSWORD
) -> httpx.Response:
    return await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
        headers=await csrf_headers(client),
    )


@asynccontextmanager
async def logged_in_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client(app) as client:
        resp = await login(client)
        assert resp.status_code == 200, resp.text
        yield client


async def add_mock_model(client: httpx.AsyncClient, name: str = "Mock") -> dict[str, Any]:
    """Create a mock provider via the API, import its models, return the default model."""
    resp = await client.post(
        "/api/v1/providers", json={"kind": "mock", "name": name}, headers=await csrf_headers(client)
    )
    assert resp.status_code == 201, resp.text
    provider_id = resp.json()["id"]
    resp = await client.post(
        f"/api/v1/providers/{provider_id}/sync-models", headers=await csrf_headers(client)
    )
    assert resp.status_code == 200, resp.text
    models = (await client.get("/api/v1/models")).json()
    return next(m for m in models if m["is_default"])


class RecordingQueue:
    """Stands in for the ARQ queue: records which tasks were enqueued."""

    def __init__(self) -> None:
        self.enqueued: list[Any] = []

    async def enqueue_task(self, task_id: Any) -> bool:
        self.enqueued.append(task_id)
        return True

    async def close(self) -> None:
        return None


@pytest.fixture
def queue(app: FastAPI) -> RecordingQueue:
    recording = RecordingQueue()
    app.state.queue = recording
    return recording


def executor_for(app: FastAPI) -> Any:
    """The executor exactly as the worker builds it (all runtimes + scheduler hook)."""
    from app.workers.jobs import build_executor

    return build_executor(app.state.db, app.state.gateway, app.state.settings, app.state.queue)


async def drain(
    app: FastAPI, queue: RecordingQueue, *, parallel: bool = False, limit: int = 200
) -> int:
    """Run enqueued jobs like the worker would, until nothing is left. Returns job count."""
    executor = executor_for(app)
    done = 0
    while queue.enqueued and done < limit:
        if parallel:
            batch, queue.enqueued = list(queue.enqueued), []
            await asyncio.gather(*(executor.execute(t) for t in batch))
            done += len(batch)
        else:
            await executor.execute(queue.enqueued.pop(0))
            done += 1
    return done


async def create_agent(client: httpx.AsyncClient, **body: Any) -> dict[str, Any]:
    payload = {"name": "Helper", "system_prompt": "Be helpful."}
    payload.update(body)
    resp = await client.post("/api/v1/agents", json=payload, headers=await csrf_headers(client))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def run_agent(
    client: httpx.AsyncClient, agent_id: str, title: str, description: str = "", **headers: str
) -> httpx.Response:
    return await client.post(
        f"/api/v1/agents/{agent_id}/run",
        json={"title": title, "description": description},
        headers={**(await csrf_headers(client)), **headers},
    )
