"""FastAPI application factory.

Run with: ``uvicorn app.main:create_app --factory``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.db import Database
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import CSRFMiddleware, RequestContextMiddleware
from app.core.openapi import install_openapi
from app.core.redis import create_redis
from app.events.bus import EventPublisher, set_publisher
from app.events.ws import router as ws_router
from app.providers.gateway import ModelGateway
from app.services.chat_stream import ChatStreamManager, fail_orphaned_generations
from app.tasks.queue import TaskQueue

logger = logging.getLogger("moloko.app")


async def _recover(app: FastAPI) -> None:
    """Startup recovery (spec 9.1): nothing can be generating yet, so leftovers were interrupted."""
    try:
        async with app.state.db.sessionmaker() as db:
            failed = await fail_orphaned_generations(db)
        if failed:
            logger.warning("interrupted_generations_marked_failed", extra={"count": failed})
    except Exception:  # noqa: BLE001 — the DB may still be starting; health shows it
        logger.warning("startup_recovery_skipped")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.db = Database(settings)
        app.state.redis = create_redis(settings.redis_url)
        app.state.redis_pubsub = create_redis(settings.redis_url, socket_timeout=None)
        app.state.gateway = ModelGateway(settings)
        app.state.queue = TaskQueue(settings.redis_url)
        set_publisher(EventPublisher(app.state.redis))
        app.state.chat_streams = ChatStreamManager(app.state.db.sessionmaker, app.state.gateway)
        await _recover(app)
        logger.info("startup", extra={"environment": settings.environment})
        try:
            yield
        finally:
            await app.state.chat_streams.shutdown()
            await app.state.queue.close()
            await app.state.redis_pubsub.aclose()
            await app.state.redis.aclose()
            await app.state.db.dispose()
            logger.info("shutdown")

    dev = settings.is_development
    app = FastAPI(
        title="moloko API",
        version=__version__,
        lifespan=lifespan,
        openapi_url="/api/v1/openapi.json" if dev else None,
        docs_url="/api/docs" if dev else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.version = __version__

    install_error_handlers(app)
    app.include_router(api_router)
    app.include_router(ws_router)
    install_openapi(app)

    # Starlette runs the last-added middleware first.
    app.add_middleware(CSRFMiddleware, settings=settings)
    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Content-Type", settings.csrf_header_name, "Idempotency-Key"],
        )
    app.add_middleware(RequestContextMiddleware)
    return app
