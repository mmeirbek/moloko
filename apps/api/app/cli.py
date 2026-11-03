"""Admin CLI. There is no public registration: the owner account is created here.

python -m app.cli create-owner --username me
python -m app.cli reset-password --username me
python -m app.cli wait-for-db --timeout 60
python -m app.cli has-owner              # exit 0 if the owner account exists (deploy script)
python -m app.cli set-address --username me --address "Мейрбек Максатович"
python -m app.cli set-address --username me --clear
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
import time

from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.core.db import Database
from app.core.errors import AppError
from app.services.users import UserService


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass("Password: ")
    second = getpass.getpass("Repeat password: ")
    if first != second:
        raise SystemExit("Passwords do not match.")
    return first


async def _create_owner(args: argparse.Namespace) -> None:
    password = _read_password(args.password_stdin)
    db = Database(get_settings())
    try:
        async with db.sessionmaker() as session:
            user = await UserService(session).create_owner(
                args.username, password, args.display_name
            )
        print(f"Owner '{user.username}' created.")
    finally:
        await db.dispose()


async def _has_owner(args: argparse.Namespace) -> None:
    from sqlalchemy import func, select

    from app.models.user import User

    db = Database(get_settings())
    try:
        async with db.sessionmaker() as session:
            count = (await session.execute(select(func.count()).select_from(User))).scalar()
    finally:
        await db.dispose()
    print("yes" if count else "no")
    if not count:
        raise SystemExit(1)


async def _reset_password(args: argparse.Namespace) -> None:
    password = _read_password(args.password_stdin)
    db = Database(get_settings())
    try:
        async with db.sessionmaker() as session:
            user = await UserService(session).reset_password(args.username, password)
        print(f"Password for '{user.username}' changed; all sessions were signed out.")
    finally:
        await db.dispose()


async def _set_address(args: argparse.Namespace) -> None:
    settings = get_settings()
    db = Database(settings)
    try:
        async with db.sessionmaker() as session:
            user = await UserService(session).set_address_as(
                args.username,
                None if args.clear else args.address,
                address_as_max_chars=settings.address_as_max_chars,
            )
    finally:
        await db.dispose()
    if user.address_as is None:
        print(f"moloko no longer uses a particular form of address for '{user.username}'.")
    else:
        print(f"moloko now addresses '{user.username}' as «{user.address_as}».")


async def _remember(args: argparse.Namespace) -> None:
    """A pinned shared memory about the owner (all agents and the chat see it), read from
    stdin. The same title updates the entry (a new revision) instead of adding another."""
    from sqlalchemy import select

    from app.agents.state import MemoryType
    from app.models.memory import Memory
    from app.repositories.users import UserRepository
    from app.schemas.memories import MemoryCreate, MemoryUpdate
    from app.services.memories import MemoryService

    content = sys.stdin.read().strip()
    if not content:
        raise SystemExit("Nothing to remember: pass the text on stdin.")
    settings = get_settings()
    db = Database(settings)
    try:
        async with db.sessionmaker() as session:
            user = await UserRepository(session).get_by_username(args.username.strip().lower())
            if user is None:
                raise SystemExit(f"No user '{args.username}'.")
            existing = (
                await session.execute(
                    select(Memory).where(
                        Memory.user_id == user.id,
                        Memory.agent_id.is_(None),
                        Memory.memory_type == MemoryType.USER.value,
                        Memory.title == args.title.strip(),
                    )
                )
            ).scalar_one_or_none()
            service = MemoryService(session, settings)
            if existing is None:
                memory = await service.create(
                    user.id,
                    MemoryCreate(
                        memory_type=MemoryType.USER, title=args.title, content=content, pinned=True
                    ),
                )
            else:
                memory = await service.update(
                    user.id, existing.id, MemoryUpdate(content=content, pinned=True)
                )
            title, revision = memory.title, memory.revision
    finally:
        await db.dispose()
    print(f"Remembered «{title}» for every agent and the chat (pinned, revision {revision}).")


async def _wait_for_db(args: argparse.Namespace) -> None:
    from sqlalchemy import text

    url = get_settings().database_url
    deadline = time.monotonic() + args.timeout
    engine = create_async_engine(url)
    try:
        while True:
            try:
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
                print("Database is reachable.")
                return
            except Exception as exc:  # noqa: BLE001 — retry on any connection error
                if time.monotonic() >= deadline:
                    raise SystemExit(f"Database not reachable: {type(exc).__name__}") from None
                await asyncio.sleep(1)
    finally:
        await engine.dispose()


async def _wait_for_migrations(args: argparse.Namespace) -> None:
    """Block until the database schema is at the latest Alembic revision (used by the worker)."""
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    ini = str(Path(__file__).parent.parent / "alembic.ini")
    head = ScriptDirectory.from_config(Config(ini)).get_current_head()
    engine = create_async_engine(get_settings().database_url)
    deadline = time.monotonic() + args.timeout
    try:
        while True:
            try:
                async with engine.connect() as conn:
                    query = text("SELECT version_num FROM alembic_version")
                    current = (await conn.execute(query)).scalar()
                if current == head:
                    print(f"Schema is at {head}.")
                    return
            except Exception:  # noqa: BLE001, S110 — not ready yet; retry
                pass
            if time.monotonic() >= deadline:
                raise SystemExit(f"Schema is not at {head} yet.")
            await asyncio.sleep(1)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-owner", help="Create the single owner account")
    p.add_argument("--username", required=True)
    p.add_argument("--display-name", default=None)
    p.add_argument("--password-stdin", action="store_true", help="Read the password from stdin")
    p.set_defaults(func=_create_owner)

    p = sub.add_parser("reset-password", help="Set a new password and sign out all sessions")
    p.add_argument("--username", required=True)
    p.add_argument("--password-stdin", action="store_true")
    p.set_defaults(func=_reset_password)

    p = sub.add_parser("set-address", help="Set how moloko addresses the user in every answer")
    p.add_argument("--username", required=True)
    what = p.add_mutually_exclusive_group(required=True)
    what.add_argument("--address", help='The form of address, e.g. "Мейрбек Максатович"')
    what.add_argument("--clear", action="store_true", help="No particular form of address")
    p.set_defaults(func=_set_address)

    p = sub.add_parser(
        "remember", help="Save a pinned memory about the user (text on stdin) for agents and chat"
    )
    p.add_argument("--username", required=True)
    p.add_argument("--title", required=True, help="Same title = update that entry")
    p.set_defaults(func=_remember)

    p = sub.add_parser("has-owner", help="Exit 0 if the owner account exists, 1 if not")
    p.set_defaults(func=_has_owner)

    p = sub.add_parser("wait-for-db", help="Block until PostgreSQL accepts connections")
    p.add_argument("--timeout", type=float, default=60)
    p.set_defaults(func=_wait_for_db)

    p = sub.add_parser("wait-for-migrations", help="Block until the schema is at the latest head")
    p.add_argument("--timeout", type=float, default=120)
    p.set_defaults(func=_wait_for_migrations)

    args = parser.parse_args(argv)
    try:
        asyncio.run(args.func(args))
    except AppError as exc:
        raise SystemExit(f"Error: {exc.message}") from None


if __name__ == "__main__":
    main()
