"""The chat hands work to the agents by itself (owner's decision 2026-11-03: a simple
question gets a quick answer from the model, work becomes a task by itself).

The chat model is told what the office's agents can do; when the owner's message asks for
such work, it answers only with ``HANDOFF_MARKER``. That answer is never shown: the message
goes to the Orchestrator as a task linked to the chat (its final answer is posted back into
the chat, as with the «Агентам» switch), and the owner's message links to the agents' work.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.events import bus
from app.models.chat import Message
from app.providers.base import ChatRequest, ChatResult
from app.providers.mock_provider import last_user_text, register_scripted_handler
from app.tasks.queue import TaskEnqueuer

logger = logging.getLogger("moloko.chat")

HANDOFF_MARKER = "[[agents]]"

HANDOFF_INSTRUCTION = (
    "You are the chat of the owner's AI office. Its agents can do real work: change code "
    "and files, work in GitHub repositories, run commands and tests, browse websites, and "
    "carry out jobs of several steps. When the owner's latest message asks for such work to "
    f"be done (not only explained), reply with exactly {HANDOFF_MARKER} and nothing else — "
    "the message then goes to the agents as a task. Answer everything else yourself: "
    "questions, explanations, advice, short texts."
)


@dataclass(frozen=True)
class Handoff:
    """What a chat answer needs to hand its question to the agents."""

    queue: TaskEnqueuer | None
    content: str
    title_chars: int


def wants_agents(text: str) -> bool:
    """The model's answer asks to hand the message to the agents."""
    return text.strip().startswith(HANDOFF_MARKER)


async def hand_to_agents(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    answer_id: uuid.UUID,
    handoff: Handoff,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Start the Orchestrator on the owner's message; the marker answer is removed and the
    owner's message links to the run. Returns (task id, run id); raises when the agents
    cannot take it now (engine stopped, budget, the Orchestrator busy)."""
    from app.orchestrator.service import start_orchestrated_run
    from app.services.chat import make_title

    async with sessionmaker() as db:
        task, run = await start_orchestrated_run(
            db,
            handoff.queue,
            user_id,
            title=make_title(handoff.content, handoff.title_chars),
            description=handoff.content,
            conversation_id=conversation_id,
        )
        answer = await db.get(Message, answer_id)
        question = None
        if answer is not None:
            question = (
                await db.execute(
                    select(Message.id)
                    .where(
                        Message.conversation_id == conversation_id,
                        Message.role == "user",
                        Message.created_at < answer.created_at,
                    )
                    .order_by(Message.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if question is not None:
            await db.execute(
                update(Message).where(Message.id == question).values(agent_run_id=run.id)
            )
        await db.execute(delete(Message).where(Message.id == answer_id))
        await bus.emit(
            db,
            user_id=user_id,
            type="chat.message_completed",
            payload={
                "conversation_id": str(conversation_id),
                "handed_off": {"message_id": str(answer_id), "task_id": str(task.id)},
            },
        )
        await bus.commit(db)
    logger.info("chat_handed_off", extra={"task_id": str(task.id), "run_id": str(run.id)})
    return task.id, run.id


def _scripted(req: ChatRequest) -> ChatResult | None:
    """Mock provider: ``[[mock:work]]`` in a chat message is work for the agents."""
    if req.system and HANDOFF_MARKER in req.system and "[[mock:work]]" in last_user_text(req):
        return ChatResult(text=HANDOFF_MARKER, model=req.model)
    return None


register_scripted_handler(_scripted)
