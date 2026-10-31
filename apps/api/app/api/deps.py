from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import Database
from app.services.auth import AuthContext, AuthService, ClientInfo


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_database(request: Request) -> Database:
    db: Database = request.app.state.db
    return db


async def get_db_session(
    database: Annotated[Database, Depends(get_database)],
) -> AsyncIterator[AsyncSession]:
    async with database.sessionmaker() as session:
        yield session


def get_client_info(request: Request) -> ClientInfo:
    return ClientInfo(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


async def require_auth(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> AuthContext:
    token = request.cookies.get(settings.session_cookie_name)
    ctx = await AuthService(db, settings).authenticate(token)
    request.state.auth = ctx
    return ctx


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
CurrentAuth = Annotated[AuthContext, Depends(require_auth)]
Client = Annotated[ClientInfo, Depends(get_client_info)]
