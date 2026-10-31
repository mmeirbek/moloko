"""WebSocket gateway ``/ws/v1/events`` (spec 11).

    client → {"type": "hello", "last_seq": 12000 | null, "csrf": "<token>"}
    server → {"type": "snapshot", ...}  when last_seq is null / too old / too far behind
             {"type": "event", "event": {...envelope}}  replayed after last_seq …
             {"type": "resumed", "seq": N}  … then this marker, then live events
    (the envelope is nested: its own ``type`` field would collide with the frame type)
    client ↔ {"type": "ping"} / {"type": "pong"}

* Auth: the session cookie. The ``hello`` must also carry the CSRF token (bound to that
  session), which a cross-site page cannot read — this blocks cross-site WebSocket hijacking.
* Redis pub/sub is only an accelerator: every couple of seconds the gateway also reads
  new events from PostgreSQL, so a Redis outage delays events but never loses them.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.errors import NotAuthenticated
from app.core.security import csrf_binding, verify_csrf_token
from app.events.bus import channel, envelope
from app.events.snapshot import build_snapshot, current_seq, missed_count
from app.models.event import AgentEvent
from app.services.auth import AuthService

logger = logging.getLogger("moloko.ws")
router = APIRouter()

CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_BAD_REQUEST = 4400
DB_POLL_SECONDS = 2.0
SESSION_RECHECK_SECONDS = 60.0
HELLO_TIMEOUT = 10.0


async def _events_after(
    ws: WebSocket, user_id: uuid.UUID, after: int, limit: int
) -> list[dict[str, Any]]:
    async with ws.app.state.db.sessionmaker() as db:
        rows = await db.execute(
            select(AgentEvent)
            .where(AgentEvent.user_id == user_id, AgentEvent.seq > after)
            .order_by(AgentEvent.seq)
            .limit(limit)
        )
        return [envelope(e) for e in rows.scalars()]


@router.websocket("/ws/v1/events")
async def events_socket(ws: WebSocket) -> None:
    settings = ws.app.state.settings
    token = ws.cookies.get(settings.session_cookie_name)
    try:
        async with ws.app.state.db.sessionmaker() as db:
            auth = await AuthService(db, settings).authenticate(token)
    except NotAuthenticated:
        await ws.close(code=CLOSE_UNAUTHENTICATED)
        return
    user_id = auth.user.id
    session_id = auth.session.id
    await ws.accept()

    try:
        hello = await asyncio.wait_for(ws.receive_json(), timeout=HELLO_TIMEOUT)
    except (TimeoutError, WebSocketDisconnect, json.JSONDecodeError, KeyError):
        await ws.close(code=CLOSE_BAD_REQUEST)
        return
    if not isinstance(hello, dict) or hello.get("type") != "hello":
        await ws.close(code=CLOSE_BAD_REQUEST)
        return
    if not verify_csrf_token(
        settings.secret_key.get_secret_value(), hello.get("csrf"), csrf_binding(token)
    ):
        await ws.close(code=CLOSE_FORBIDDEN)
        return

    live: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=5000)
    pubsub = ws.app.state.redis_pubsub.pubsub()
    reader: asyncio.Task[None] | None = None

    async def read_pubsub() -> None:
        try:
            async for message in pubsub.listen():
                if message.get("type") == "message":
                    with contextlib.suppress(asyncio.QueueFull, json.JSONDecodeError):
                        live.put_nowait(json.loads(message["data"]))
        except Exception as exc:  # noqa: BLE001 — fall back to DB polling
            logger.warning("ws_pubsub_lost", extra={"error": type(exc).__name__})

    try:
        await pubsub.subscribe(channel(user_id))  # subscribe BEFORE reading state: no gap
        reader = asyncio.create_task(read_pubsub())
    except Exception as exc:  # noqa: BLE001
        logger.warning("ws_pubsub_unavailable", extra={"error": type(exc).__name__})

    sent_seq = 0
    last_seq = hello.get("last_seq")
    try:
        async with ws.app.state.db.sessionmaker() as db:
            head = await current_seq(db, user_id)
            # The event log is never pruned in the MVP, so any last_seq ≤ head is replayable;
            # only "too far behind" falls back to a snapshot. "Behind" = how many of THIS
            # user's events were missed (seq is global and has gaps, so never subtract seqs).
            # If pruning is added, also snapshot when last_seq is below the prune watermark.
            replayable = (
                isinstance(last_seq, int)
                and not isinstance(last_seq, bool)
                and 0 <= last_seq <= head
                and await missed_count(db, user_id, last_seq, settings.realtime_max_replay + 1)
                <= settings.realtime_max_replay
            )
            if not replayable:
                snapshot = await build_snapshot(db, user_id)
                await ws.send_json(snapshot)
                sent_seq = snapshot["seq"]
        if replayable:
            assert isinstance(last_seq, int)
            for event in await _events_after(ws, user_id, last_seq, settings.realtime_max_replay):
                await ws.send_json({"type": "event", "event": event})
                sent_seq = event["seq"]
            sent_seq = max(sent_seq, last_seq)
            # Always confirm the resume — even with nothing missed the client must
            # learn that it is caught up (otherwise it cannot tell "live" from "stuck").
            await ws.send_json({"type": "resumed", "seq": sent_seq})

        async def receive_loop() -> None:
            while True:
                message = await ws.receive_json()
                if isinstance(message, dict) and message.get("type") == "ping":
                    await ws.send_json({"type": "pong"})

        receiver = asyncio.create_task(receive_loop())
        loop = asyncio.get_running_loop()
        next_session_check = loop.time() + SESSION_RECHECK_SECONDS
        try:
            while not receiver.done():
                try:
                    event = await asyncio.wait_for(live.get(), timeout=DB_POLL_SECONDS)
                    batch = [event]
                except TimeoutError:
                    batch = await _events_after(ws, user_id, sent_seq, 200)
                for event in batch:
                    seq = event.get("seq")
                    if seq is None:  # ephemeral (e.g. chat.message_delta)
                        await ws.send_json({"type": "event", "event": event})
                        continue
                    if seq <= sent_seq:
                        continue  # duplicate (already replayed / polled)
                    if seq > sent_seq + 1:
                        # A gap: fill it from the database in order before sending this one.
                        for missed in await _events_after(ws, user_id, sent_seq, seq - sent_seq):
                            if missed["seq"] < seq:
                                await ws.send_json({"type": "event", "event": missed})
                                sent_seq = missed["seq"]
                    await ws.send_json({"type": "event", "event": event})
                    sent_seq = seq
                if loop.time() >= next_session_check:
                    next_session_check = loop.time() + SESSION_RECHECK_SECONDS
                    async with ws.app.state.db.sessionmaker() as db:
                        try:
                            current = await AuthService(db, settings).authenticate(token)
                        except NotAuthenticated:
                            current = None
                    if current is None or current.session.id != session_id:
                        await ws.close(code=CLOSE_UNAUTHENTICATED)
                        return
        finally:
            receiver.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await receiver
    except WebSocketDisconnect:
        pass
    finally:
        if reader is not None:
            reader.cancel()
        with contextlib.suppress(Exception):
            await pubsub.aclose()
