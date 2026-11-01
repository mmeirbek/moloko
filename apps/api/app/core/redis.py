"""Redis client. Redis is for queues, caches and pub/sub only — never the sole
store of any state (spec invariant 2)."""

from __future__ import annotations

from redis.asyncio import Redis


def create_redis(url: str, *, socket_timeout: float | None = 2.0) -> Redis:
    """``socket_timeout=None`` for pub/sub listeners, which legitimately wait for long."""
    client: Redis = Redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=socket_timeout,
        health_check_interval=30,
    )
    return client
