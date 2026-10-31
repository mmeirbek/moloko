"""Server-Sent Events helpers (chat token streaming — see docs/decisions.md)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi.responses import StreamingResponse

HEARTBEAT_SECONDS = 15.0


def sse_event(name: str, data: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(data, default=str, ensure_ascii=False)}\n\n"


async def queue_events(
    queue: asyncio.Queue[tuple[str, dict[str, Any]] | None],
) -> AsyncIterator[str]:
    """Yield SSE frames from ``queue`` until it is closed (``None``), with heartbeats."""
    while True:
        try:
            item = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
        except TimeoutError:
            yield ": ping\n\n"
            continue
        if item is None:
            return
        yield sse_event(*item)


def sse_response(body: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        body,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
