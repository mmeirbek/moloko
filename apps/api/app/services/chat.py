"""Conversations and messages (spec 2.1 Chat, Sprint 2)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import Conflict, NotFound
from app.models.chat import Conversation, Message
from app.models.provider import ModelConfig
from app.providers.base import ChatMessage, ChatRequest
from app.providers.gateway import ModelGateway, ModelUnavailable
from app.schemas.chat import ConversationCreate, ConversationUpdate
from app.schemas.common import decode_cursor, encode_cursor
from app.services.audit import AuditService
from app.services.chat_stream import ChatStreamManager, StreamState

DEFAULT_TITLE = "New chat"


class GenerationInProgress(Conflict):
    code = "generation_in_progress"
    message = "Wait for the current answer to finish (or stop it) before sending another message."


def make_title(content: str, max_chars: int) -> str:
    line = " ".join(content.split())
    return line if len(line) <= max_chars else line[: max_chars - 1].rstrip() + "…"


class ChatService:
    def __init__(self, db: AsyncSession, settings: Settings, gateway: ModelGateway) -> None:
        self.db = db
        self.settings = settings
        self.gateway = gateway
        self.audit = AuditService(db)

    # --- conversations -------------------------------------------------------------

    async def get(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> Conversation:
        conv = await self.db.get(Conversation, conversation_id)
        if conv is None or conv.user_id != user_id:
            raise NotFound("Conversation not found.")
        return conv

    async def _check_model(self, user_id: uuid.UUID, model_config_id: uuid.UUID | None) -> None:
        if model_config_id is None:
            return
        config = await self.db.get(ModelConfig, model_config_id)
        if config is None or config.user_id != user_id:
            raise ModelUnavailable("The selected model does not exist.")

    async def list_conversations(
        self, user_id: uuid.UUID, *, limit: int, cursor: str | None
    ) -> tuple[list[Conversation], str | None]:
        query = select(Conversation).where(Conversation.user_id == user_id)
        if cursor:
            at, cid = decode_cursor(cursor)
            query = query.where(
                or_(
                    Conversation.last_message_at < at,
                    and_(Conversation.last_message_at == at, Conversation.id < cid),
                )
            )
        rows = list(
            (
                await self.db.execute(
                    query.order_by(
                        Conversation.last_message_at.desc(), Conversation.id.desc()
                    ).limit(limit + 1)
                )
            ).scalars()
        )
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            next_cursor = encode_cursor(rows[-1].last_message_at, rows[-1].id)
        return rows, next_cursor

    async def create(self, user_id: uuid.UUID, data: ConversationCreate) -> Conversation:
        await self._check_model(user_id, data.model_config_id)
        conv = Conversation(
            user_id=user_id,
            title=data.title or DEFAULT_TITLE,
            model_config_id=data.model_config_id,
            last_message_at=datetime.now(UTC),
        )
        self.db.add(conv)
        await self.db.commit()
        await self.db.refresh(conv)
        return conv

    async def update(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, data: ConversationUpdate
    ) -> Conversation:
        conv = await self.get(user_id, conversation_id)
        if data.title is not None:
            conv.title = data.title
        if "model_config_id" in data.model_fields_set:
            await self._check_model(user_id, data.model_config_id)
            conv.model_config_id = data.model_config_id
        await self.db.commit()
        await self.db.refresh(conv)
        return conv

    async def delete(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
        conv = await self.get(user_id, conversation_id)
        await self.db.delete(conv)
        await self.audit.record(
            "conversation.deleted",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="conversation",
            resource_id=str(conversation_id),
        )
        await self.db.commit()

    # --- messages --------------------------------------------------------------------

    async def messages(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, *, limit: int, cursor: str | None
    ) -> tuple[list[Message], str | None]:
        """Newest page first; items inside a page are oldest → newest. ``next_cursor`` = older."""
        await self.get(user_id, conversation_id)
        query = select(Message).where(Message.conversation_id == conversation_id)
        if cursor:
            at, mid = decode_cursor(cursor)
            query = query.where(
                or_(Message.created_at < at, and_(Message.created_at == at, Message.id < mid))
            )
        rows = list(
            (
                await self.db.execute(
                    query.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit + 1)
                )
            ).scalars()
        )
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id)
        rows.reverse()
        return rows, next_cursor

    async def get_message(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, message_id: uuid.UUID
    ) -> Message:
        await self.get(user_id, conversation_id)
        message = await self.db.get(Message, message_id)
        if message is None or message.conversation_id != conversation_id:
            raise NotFound("Message not found.")
        return message

    async def _context(self, conversation_id: uuid.UUID) -> list[ChatMessage]:
        rows = (
            await self.db.execute(
                select(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.status == "completed",
                    Message.role.in_(("user", "assistant")),
                )
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(self.settings.chat_context_max_messages - 1)
            )
        ).scalars()
        history = [ChatMessage(role=m.role, content=m.content) for m in reversed(list(rows))]  # type: ignore[arg-type]
        return history

    async def send(
        self,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        content: str,
        model_config_id: uuid.UUID | None,
        streams: ChatStreamManager,
    ) -> tuple[Message, Message, StreamState]:
        # Row lock: two concurrent sends to one conversation are serialised here.
        conv = (
            await self.db.execute(
                select(Conversation).where(Conversation.id == conversation_id).with_for_update()
            )
        ).scalar_one_or_none()
        if conv is None or conv.user_id != user_id:
            raise NotFound("Conversation not found.")
        busy = await self.db.execute(
            select(Message.id)
            .where(Message.conversation_id == conversation_id, Message.status == "streaming")
            .limit(1)
        )
        if busy.first() is not None:
            raise GenerationInProgress()

        target = await self.gateway.resolve(
            self.db, user_id, model_config_id or conv.model_config_id
        )
        history = await self._context(conversation_id)

        now = datetime.now(UTC)
        user_msg = Message(
            conversation_id=conversation_id,
            user_id=user_id,
            role="user",
            content=content,
            status="completed",
            created_at=now,
            completed_at=now,
        )
        assistant_msg = Message(
            conversation_id=conversation_id,
            user_id=user_id,
            role="assistant",
            content="",
            status="streaming",
            model_config_id=target.model_config_id,
            provider_kind=target.provider_kind,
            model=target.model,
            created_at=now + timedelta(microseconds=1),  # strictly after the question
        )
        self.db.add_all([user_msg, assistant_msg])
        if conv.title == DEFAULT_TITLE and not history:
            conv.title = make_title(content, self.settings.chat_title_max_chars)
        if model_config_id is not None:
            conv.model_config_id = model_config_id
        conv.last_message_at = now
        await self.db.commit()

        request = ChatRequest(
            model=target.model,
            messages=(*history, ChatMessage(role="user", content=content)),
        )
        state = streams.start(
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=assistant_msg.id,
            target=target,
            request=request,
        )
        return user_msg, assistant_msg, state
