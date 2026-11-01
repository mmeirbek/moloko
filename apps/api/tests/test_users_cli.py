from __future__ import annotations

import io

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app import cli
from app.core.config import get_settings
from app.core.errors import Conflict
from app.models import User
from app.services.users import InvalidInput, UserService
from tests.conftest import OWNER_PASSWORD, TEST_DATABASE_URL, TEST_REDIS_URL, login


async def test_only_one_owner_can_be_created(app: FastAPI, owner: User) -> None:
    async with app.state.db.sessionmaker() as s:
        with pytest.raises(Conflict):
            await UserService(s).create_owner("second", "another long password")


@pytest.mark.parametrize("username", ["ab", "-leading", "has space", "UPPER!", "x" * 65])
async def test_create_owner_rejects_bad_usernames(app: FastAPI, username: str) -> None:
    async with app.state.db.sessionmaker() as s:
        with pytest.raises(InvalidInput):
            await UserService(s).create_owner(username, "a long enough password")


async def test_create_owner_rejects_short_password(app: FastAPI) -> None:
    async with app.state.db.sessionmaker() as s:
        with pytest.raises(InvalidInput):
            await UserService(s).create_owner("owner", "short")


async def test_reset_password_signs_out_everywhere(
    app: FastAPI, client: httpx.AsyncClient, owner: User
) -> None:
    assert (await login(client)).status_code == 200
    async with app.state.db.sessionmaker() as s:
        await UserService(s).reset_password("owner", "a brand new password")
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert (await login(client, password=OWNER_PASSWORD)).status_code == 401
    assert (await login(client, password="a brand new password")).status_code == 200


def test_cli_create_owner_from_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", TEST_REDIS_URL)
    monkeypatch.setenv("SECRET_KEY", "cli-test-secret-" + "y" * 32)
    monkeypatch.setattr("sys.stdin", io.StringIO("cli password long enough\n"))
    get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit):
            cli.main(["has-owner"])  # none yet: the deploy script asks to create one
        cli.main(["create-owner", "--username", "CliOwner", "--password-stdin"])
        cli.main(["has-owner"])
        with pytest.raises(SystemExit, match="already exists"):
            monkeypatch.setattr("sys.stdin", io.StringIO("cli password long enough\n"))
            cli.main(["create-owner", "--username", "other", "--password-stdin"])
    finally:
        get_settings.cache_clear()

    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    async def fetch() -> list[str]:
        engine = create_async_engine(TEST_DATABASE_URL)
        try:
            async with engine.connect() as conn:
                return list((await conn.execute(select(User.username))).scalars())
        finally:
            await engine.dispose()

    assert asyncio.run(fetch()) == ["cliowner"]
