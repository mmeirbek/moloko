from __future__ import annotations

import asyncio
import logging

from redis.asyncio import Redis

from app.core.db import Database
from app.schemas.health import CheckStatus, HealthChecks, HealthResponse

logger = logging.getLogger("moloko.health")

CHECK_TIMEOUT_SECONDS = 2.0


async def _check(name: str, coro: object) -> CheckStatus:
    try:
        await asyncio.wait_for(coro, timeout=CHECK_TIMEOUT_SECONDS)  # type: ignore[arg-type]
        return "ok"
    except Exception as exc:  # noqa: BLE001 — health checks must never raise
        logger.warning("health_check_failed", extra={"check": name, "error": type(exc).__name__})
        return "error"


async def check_health(db: Database, redis: Redis, version: str) -> HealthResponse:
    database, redis_status = await asyncio.gather(
        _check("database", db.ping()),
        _check("redis", redis.ping()),
    )
    checks = HealthChecks(database=database, redis=redis_status)
    status = "ok" if database == "ok" and redis_status == "ok" else "degraded"
    return HealthResponse(status=status, version=version, checks=checks)
