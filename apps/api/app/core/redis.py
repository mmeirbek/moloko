"""Redis client. Redis is for queues, caches and pub/sub only — never the sole
store of any state (spec invariant 2)."""

from __future__ import annotations

from redis.asyncio import Redis


def create_redis(url: str) -> Redis:
    return Redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
        health_check_interval=30,
    )
