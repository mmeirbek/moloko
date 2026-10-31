from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Query, Response, status

from app.api.deps import ChatStreamsDep, CurrentAuth, DbSession, GatewayDep, SettingsDep
from app.api.sse import queue_events, sse_event, sse_response
from app.schemas.chat import (
    CancelResult,
    ConversationCreate,
    ConversationOut,
    ConversationUpdate,
    MessageCreate,
    MessageOut,
)
from app.schemas.common import Page
from app.services.chat import ChatService

router = APIRouter(prefix="/chats", tags=["chats"])

SSE_DOC: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "Server-Sent Events: message.created, message.delta, "
        "message.completed | message.failed",
        "content": {"text/event-stream": {}},
    }
}


@router.get("", response_model=Page[ConversationOut])
async def list_chats(
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    gateway: GatewayDep,
    limit: int = Query(30, ge=1, le=100),
    cursor: str | None = None,
) -> Page[ConversationOut]:
    rows, next_cursor = await ChatService(db, settings, gateway).list_conversations(
        ctx.user.id, limit=limit, cursor=cursor
    )
    return Page(items=[ConversationOut.model_validate(c) for c in rows], next_cursor=next_cursor)


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_chat(
    body: ConversationCreate,
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    gateway: GatewayDep,
) -> ConversationOut:
    return ConversationOut.model_validate(
        await ChatService(db, settings, gateway).create(ctx.user.id, body)
    )


@router.get("/{chat_id}", response_model=ConversationOut)
async def get_chat(
    chat_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, settings: SettingsDep, gateway: GatewayDep
) -> ConversationOut:
    return ConversationOut.model_validate(
        await ChatService(db, settings, gateway).get(ctx.user.id, chat_id)
    )


@router.patch("/{chat_id}", response_model=ConversationOut)
async def update_chat(
    chat_id: uuid.UUID,
    body: ConversationUpdate,
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    gateway: GatewayDep,
) -> ConversationOut:
    conv = await ChatService(db, settings, gateway).update(ctx.user.id, chat_id, body)
    return ConversationOut.model_validate(conv)


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(
    chat_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, settings: SettingsDep, gateway: GatewayDep
) -> Response:
    await ChatService(db, settings, gateway).delete(ctx.user.id, chat_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{chat_id}/messages", response_model=Page[MessageOut])
async def list_messages(
    chat_id: uuid.UUID,
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    gateway: GatewayDep,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
) -> Page[MessageOut]:
    rows, next_cursor = await ChatService(db, settings, gateway).messages(
        ctx.user.id, chat_id, limit=limit, cursor=cursor
    )
    return Page(items=[MessageOut.model_validate(m) for m in rows], next_cursor=next_cursor)


@router.post(
    "/{chat_id}/messages", responses=SSE_DOC, summary="Send a message (streams the answer)"
)
async def send_message(
    chat_id: uuid.UUID,
    body: MessageCreate,
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    gateway: GatewayDep,
    streams: ChatStreamsDep,
) -> Response:
    user_msg, assistant_msg, _ = await ChatService(db, settings, gateway).send(
        ctx.user.id, chat_id, body.content, body.model_config_id, streams
    )
    # Subscribe before yielding control so no token is missed.
    subscription = streams.subscribe(assistant_msg.id)
    created = {
        "user_message": MessageOut.model_validate(user_msg).model_dump(mode="json"),
        "assistant_message": MessageOut.model_validate(assistant_msg).model_dump(mode="json"),
    }

    async def events() -> AsyncIterator[str]:
        yield sse_event("message.created", created)
        if subscription is None:
            return
        queue, _ = subscription
        try:
            async for frame in queue_events(queue):
                yield frame
        finally:
            # The browser may leave; the generation keeps running and is saved anyway.
            streams.unsubscribe(assistant_msg.id, queue)

    return sse_response(events())


@router.get(
    "/{chat_id}/messages/{message_id}/stream",
    responses=SSE_DOC,
    summary="Re-attach to an answer that is still being generated",
)
async def attach_stream(
    chat_id: uuid.UUID,
    message_id: uuid.UUID,
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    gateway: GatewayDep,
    streams: ChatStreamsDep,
) -> Response:
    message = await ChatService(db, settings, gateway).get_message(ctx.user.id, chat_id, message_id)
    subscription = streams.subscribe(message_id)
    final = MessageOut.model_validate(message).model_dump(mode="json")

    async def events() -> AsyncIterator[str]:
        if subscription is None:  # already finished: send the saved result
            name = "message.completed" if final["status"] == "completed" else "message.failed"
            yield sse_event(name, {"message": final})
            return
        queue, text_so_far = subscription
        try:
            yield sse_event(
                "message.snapshot", {"message_id": str(message_id), "text": text_so_far}
            )
            async for frame in queue_events(queue):
                yield frame
        finally:
            streams.unsubscribe(message_id, queue)

    return sse_response(events())


@router.post("/{chat_id}/messages/{message_id}/cancel", response_model=CancelResult)
async def cancel_message(
    chat_id: uuid.UUID,
    message_id: uuid.UUID,
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    gateway: GatewayDep,
    streams: ChatStreamsDep,
) -> CancelResult:
    await ChatService(db, settings, gateway).get_message(ctx.user.id, chat_id, message_id)
    return CancelResult(cancelled=await streams.cancel(message_id, ctx.user.id))
