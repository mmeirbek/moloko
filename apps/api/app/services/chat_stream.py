"""Runs assistant generations in the background and fans their tokens out.

A generation is an asyncio task owned by the API process — not by the HTTP request.
If the browser disconnects, the answer still completes and is saved; any device can
re-attach to a running generation (``subscribe``) or read the saved result later.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, new_error_id
from app.events import bus
from app.models.chat import Conversation, Message
from app.providers.base import ChatRequest, ChatResult, ProviderError
from app.providers.gateway import ModelGateway, ModelTarget, estimate_cost
from app.schemas.chat import MessageOut
from app.services import chat_memory
from app.services.chat_handoff import Handoff, hand_to_agents, wants_agents
from app.tasks.queue import TaskEnqueuer

logger = logging.getLogger("moloko.chat")

StreamEvent = tuple[str, dict[str, Any]]
# Called for every event (e.g. to publish it to other devices). Must not raise.
EventHook = Callable[[uuid.UUID, StreamEvent], Awaitable[None]]

INTERRUPTED_CODE = "interrupted"
INTERRUPTED_MESSAGE = "The answer was interrupted because the server restarted."


@dataclass
class StreamState:
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    user_id: uuid.UUID
    parts: list[str] = field(default_factory=list)
    subscribers: set[asyncio.Queue[StreamEvent | None]] = field(default_factory=set)
    task: asyncio.Task[None] | None = None
    cancel_reason: Literal["user", "shutdown"] | None = None
    # Set when the chat may hand the message to the agents (services/chat_handoff).
    handoff: Handoff | None = None

    @property
    def text(self) -> str:
        return "".join(self.parts)

    def publish(self, event: StreamEvent) -> None:
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:  # a stuck reader must not block generation
                self.subscribers.discard(queue)

    def close(self) -> None:
        for queue in list(self.subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(None)
        self.subscribers.clear()


class ChatStreamManager:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        gateway: ModelGateway,
        *,
        hook: EventHook | None = None,
        task_queue: Callable[[], TaskEnqueuer | None] | None = None,
    ) -> None:
        self.sessionmaker = sessionmaker
        self.gateway = gateway
        self.hook = hook
        # The job queue for hand-offs of messages answered from the line (read when needed:
        # tests swap it after startup).
        self.task_queue = task_queue
        self._streams: dict[uuid.UUID, StreamState] = {}
        # Rolling summaries run after an answer, in the background (services/chat_memory).
        self._background: set[asyncio.Task[None]] = set()
        self._summarizing: set[uuid.UUID] = set()
        self._summarize_again: set[uuid.UUID] = set()

    def get(self, message_id: uuid.UUID) -> StreamState | None:
        return self._streams.get(message_id)

    def start(
        self,
        *,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        message_id: uuid.UUID,
        target: ModelTarget,
        request: ChatRequest,
        handoff: Handoff | None = None,
    ) -> StreamState:
        state = StreamState(
            message_id=message_id,
            conversation_id=conversation_id,
            user_id=user_id,
            handoff=handoff,
        )
        self._streams[message_id] = state
        state.task = asyncio.create_task(
            self._run(state, target, request), name=f"chat:{message_id}"
        )
        return state

    def subscribe(
        self, message_id: uuid.UUID
    ) -> tuple[asyncio.Queue[StreamEvent | None], str] | None:
        state = self._streams.get(message_id)
        if state is None:
            return None
        queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue(maxsize=10_000)
        state.subscribers.add(queue)
        return queue, state.text

    def unsubscribe(self, message_id: uuid.UUID, queue: asyncio.Queue[StreamEvent | None]) -> None:
        state = self._streams.get(message_id)
        if state is not None:
            state.subscribers.discard(queue)

    async def cancel(self, message_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        state = self._streams.get(message_id)
        if state is None or state.user_id != user_id or state.task is None or state.task.done():
            return False
        state.cancel_reason = "user"
        state.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await state.task
        return True

    async def shutdown(self) -> None:
        tasks = []
        for state in list(self._streams.values()):
            if state.task and not state.task.done():
                state.cancel_reason = "shutdown"
                state.task.cancel()
                tasks.append(state.task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for task in list(self._background):  # a summary is redone after the next answer
            task.cancel()
        await self.idle()

    async def idle(self) -> None:
        """Wait until background work (summaries) is done — for tests and shutdown."""
        while self._background:
            await asyncio.gather(*list(self._background), return_exceptions=True)

    def after_answer(self, conversation_id: uuid.UUID, target: ModelTarget) -> None:
        """Start the conversation's summary in the background (one at a time per chat;
        an answer that finishes meanwhile makes it run once more)."""
        if not self.gateway.settings.chat_summary_enabled:
            return
        if conversation_id in self._summarizing:
            self._summarize_again.add(conversation_id)
            return
        self._summarizing.add(conversation_id)
        task = asyncio.create_task(
            self._summarize(conversation_id, target), name=f"chat-summary:{conversation_id}"
        )
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _summarize(self, conversation_id: uuid.UUID, target: ModelTarget) -> None:
        try:
            while True:
                self._summarize_again.discard(conversation_id)
                try:
                    await chat_memory.summarize_conversation(
                        self.sessionmaker,
                        self.gateway,
                        self.gateway.settings,
                        conversation_id,
                        target,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 — retried after the next answer
                    logger.warning(
                        "chat_summary_failed",
                        extra={
                            "conversation_id": str(conversation_id),
                            "error": type(exc).__name__,
                            "kind": getattr(exc, "kind", None),
                        },
                    )
                    return
                if conversation_id not in self._summarize_again:
                    return
        finally:
            self._summarizing.discard(conversation_id)
            self._summarize_again.discard(conversation_id)

    async def _emit(self, state: StreamState, event: StreamEvent) -> None:
        state.publish(event)
        if self.hook is not None:
            try:
                await self.hook(state.conversation_id, event)
            except Exception:  # noqa: BLE001 — fan-out is best effort
                logger.warning("chat_hook_failed", extra={"message_id": str(state.message_id)})

    async def _run(self, state: StreamState, target: ModelTarget, request: ChatRequest) -> None:
        result: ChatResult | None = None
        try:
            async for chunk in self.gateway.stream(target, request):
                if chunk.text:
                    state.parts.append(chunk.text)
                    await self._emit(
                        state,
                        (
                            "message.delta",
                            {"message_id": str(state.message_id), "text": chunk.text},
                        ),
                    )
                    # Other devices see the answer grow live (stream-only, not stored).
                    await bus.publish_ephemeral(
                        state.user_id,
                        "chat.message_delta",
                        {
                            "conversation_id": str(state.conversation_id),
                            "message_id": str(state.message_id),
                            "text": chunk.text,
                        },
                    )
                if chunk.result is not None:
                    result = chunk.result
            await self._finish(state, target, "completed", result=result)
        except ProviderError as exc:
            await self._finish(
                state, target, "failed", error=(f"provider_{exc.kind}", exc.message, new_error_id())
            )
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if task is not None:
                task.uncancel()
            if state.cancel_reason == "user":
                await self._finish(state, target, "cancelled")
            else:
                await self._finish(
                    state,
                    target,
                    "failed",
                    error=(INTERRUPTED_CODE, INTERRUPTED_MESSAGE, new_error_id()),
                )
        except Exception:
            error_id = new_error_id()
            logger.exception("chat_generation_failed", extra={"error_id": error_id})
            await self._finish(
                state,
                target,
                "failed",
                error=(
                    "internal_error",
                    "Something went wrong while generating the answer.",
                    error_id,
                ),
            )
        finally:
            state.close()
            self._streams.pop(state.message_id, None)

    async def _hand_off(
        self, state: StreamState, target: ModelTarget, result: ChatResult | None
    ) -> bool:
        """The answer asked for the agents: start them, tell the browser. False = they could
        not take it (the answer then fails with a reason)."""
        assert state.handoff is not None
        try:
            task_id, run_id = await hand_to_agents(
                self.sessionmaker,
                user_id=state.user_id,
                conversation_id=state.conversation_id,
                answer_id=state.message_id,
                handoff=state.handoff,
            )
        except AppError as exc:
            logger.info("chat_handoff_refused", extra={"code": exc.code})
            return False
        if result is not None:
            from app.services import usage as ledger

            async with self.sessionmaker() as db:
                await ledger.record(
                    db,
                    user_id=state.user_id,
                    target=target,
                    usage=result.usage,
                    source="chat",
                    conversation_id=state.conversation_id,
                )
                await db.commit()
        await self._emit(
            state,
            (
                "message.handed_off",
                {
                    "message_id": str(state.message_id),
                    "task_id": str(task_id),
                    "run_id": str(run_id) if run_id else None,
                },
            ),
        )
        self.next_in_line(state.user_id, state.conversation_id)
        return True

    async def _finish(
        self,
        state: StreamState,
        target: ModelTarget,
        status: Literal["completed", "failed", "cancelled"],
        *,
        result: ChatResult | None = None,
        error: tuple[str, str, str] | None = None,
    ) -> None:
        now = datetime.now(UTC)
        text = state.text if result is None or not result.text else result.text
        if status == "completed" and state.handoff is not None and wants_agents(text):
            if await self._hand_off(state, target, result):
                return
            error = (
                "handoff_failed",
                "The agents could not take this now (work is stopped) — send it again later.",
                new_error_id(),
            )
            status, text = "failed", ""
        values: dict[str, Any] = {"status": status, "content": text, "completed_at": now}
        if result is not None:
            values["input_tokens"] = result.usage.input_tokens
            values["output_tokens"] = result.usage.output_tokens
            values["cost_usd"] = estimate_cost(target, result.usage)
            if result.model:
                values["model"] = result.model
        if error is not None:
            values["error_code"], values["error_message"], values["error_id"] = error
            logger.warning(
                "chat_generation_error",
                extra={"error_id": error[2], "code": error[0], "message_id": str(state.message_id)},
            )
        try:
            async with self.sessionmaker() as db:
                await db.execute(
                    update(Message).where(Message.id == state.message_id).values(**values)
                )
                await db.execute(
                    update(Conversation)
                    .where(Conversation.id == state.conversation_id)
                    .values(last_message_at=now)
                )
                message = await db.get(Message, state.message_id)
                payload = (
                    MessageOut.model_validate(message).model_dump(mode="json") if message else {}
                )
                if result is not None:
                    from app.services import usage as ledger

                    await ledger.record(
                        db,
                        user_id=state.user_id,
                        target=target,
                        usage=result.usage,
                        source="chat",
                        conversation_id=state.conversation_id,
                    )
                # The final message is persisted as an event in the same transaction (spec 10.3).
                await bus.emit(
                    db,
                    user_id=state.user_id,
                    type="chat.message_completed",
                    payload={"conversation_id": str(state.conversation_id), "message": payload},
                )
                await bus.commit(db)
        except Exception:
            logger.exception("chat_persist_failed", extra={"message_id": str(state.message_id)})
            return
        name = "message.completed" if status == "completed" else "message.failed"
        await self._emit(state, (name, {"message": payload}))
        if status == "completed":
            self.after_answer(state.conversation_id, target)
        if state.cancel_reason != "shutdown":
            self.next_in_line(state.user_id, state.conversation_id)

    def next_in_line(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
        """Answer the next message waiting in this chat (in the background)."""
        task = asyncio.create_task(
            self._answer_next(user_id, conversation_id), name=f"chat-next:{conversation_id}"
        )
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _answer_next(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
        from app.services.chat import ChatService  # chat → chat_stream at import time

        try:
            async with self.sessionmaker() as db:
                await ChatService(db, self.gateway.settings, self.gateway).answer_next(
                    user_id,
                    conversation_id,
                    self,
                    self.task_queue() if self.task_queue is not None else None,
                )
        except Exception:
            logger.exception(
                "chat_next_in_line_failed", extra={"conversation_id": str(conversation_id)}
            )

    async def resume_waiting(self) -> int:
        """After a restart: chats with messages in line and no answer running go on."""
        async with self.sessionmaker() as db:
            rows = (
                await db.execute(
                    select(Message.user_id, Message.conversation_id)
                    .where(Message.status == "queued", Message.role == "user")
                    .distinct()
                )
            ).all()
        for user_id, conversation_id in rows:
            self.next_in_line(user_id, conversation_id)
        return len(rows)


async def fail_orphaned_generations(db: AsyncSession) -> int:
    """At startup no generation can be running: mark leftovers as interrupted (not completed)."""
    result = await db.execute(
        update(Message)
        .where(Message.status == "streaming")
        .values(
            status="failed",
            error_code=INTERRUPTED_CODE,
            error_message=INTERRUPTED_MESSAGE,
            error_id=new_error_id(),
            completed_at=datetime.now(UTC),
        )
    )
    await db.commit()
    return int(getattr(result, "rowcount", 0) or 0)
