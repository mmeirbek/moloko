from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import Database
from app.providers.gateway import ModelGateway
from app.services.auth import AuthContext, AuthService, ClientInfo
from app.services.chat_stream import ChatStreamManager
from app.tasks.queue import TaskQueue


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


def get_gateway(request: Request) -> ModelGateway:
    gateway: ModelGateway = request.app.state.gateway
    return gateway


def get_chat_streams(request: Request) -> ChatStreamManager:
    streams: ChatStreamManager = request.app.state.chat_streams
    return streams


def get_queue(request: Request) -> TaskQueue:
    queue: TaskQueue = request.app.state.queue
    return queue


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
QueueDep = Annotated[TaskQueue, Depends(get_queue)]
GatewayDep = Annotated[ModelGateway, Depends(get_gateway)]
ChatStreamsDep = Annotated[ChatStreamManager, Depends(get_chat_streams)]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
CurrentAuth = Annotated[AuthContext, Depends(require_auth)]
Client = Annotated[ClientInfo, Depends(get_client_info)]
