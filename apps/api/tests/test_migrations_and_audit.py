from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.models import Base
from app.services.audit import AuditService
from tests.conftest import TEST_DATABASE_URL, run_alembic


@pytest.fixture
async def scratch_database_url() -> AsyncIterator[str]:
    """A separate, empty database so up/down migrations don't disturb other tests."""
    url = make_url(TEST_DATABASE_URL)
    name = f"{url.database}_migrations"
    admin = create_async_engine(url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield url.set(database=name).render_as_string(hide_password=False)
    finally:
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await admin.dispose()


def _diff(connection: Connection) -> list[object]:
    ctx = MigrationContext.configure(connection, opts={"compare_type": True})
    return list(compare_metadata(ctx, Base.metadata))


async def test_migrations_up_down_up_and_match_models(scratch_database_url: str) -> None:
    await run_alembic(scratch_database_url, command.upgrade, "head")
    engine = create_async_engine(scratch_database_url)
    try:
        async with engine.connect() as conn:
            assert await conn.run_sync(_diff) == [], "models and migrations disagree"
        await run_alembic(scratch_database_url, command.downgrade, "base")
        async with engine.connect() as conn:
            tables = (
                await conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
            ).scalars()
            assert set(tables) <= {"alembic_version"}
        await run_alembic(scratch_database_url, command.upgrade, "head")
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "statement",
    ["UPDATE audit_logs SET action = 'tampered'", "DELETE FROM audit_logs"],
)
async def test_audit_log_is_append_only(app: FastAPI, statement: str) -> None:
    async with app.state.db.sessionmaker() as s:
        await AuditService(s).record("test.event", "success", actor_type="system")
        await s.commit()
    async with app.state.db.sessionmaker() as s:
        with pytest.raises(DBAPIError, match="append-only"):
            await s.execute(text(statement))
