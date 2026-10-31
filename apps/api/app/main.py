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

logger = logging.getLogger("moloko.app")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.db = Database(settings)
        app.state.redis = create_redis(settings.redis_url)
        logger.info("startup", extra={"environment": settings.environment})
        try:
            yield
        finally:
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
