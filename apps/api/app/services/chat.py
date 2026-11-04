"""Conversations and messages (spec 2.1 Chat, Sprint 2)."""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import os
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, Conflict, NotFound
from app.events import bus
from app.memory.context import build_owner_context
from app.models.chat import Attachment, Conversation, Message
from app.models.provider import ModelConfig
from app.providers.base import ChatMessage, ChatRequest, ImagePart
from app.providers.gateway import ModelGateway, ModelTarget, ModelUnavailable
from app.schemas.chat import ConversationCreate, ConversationUpdate, MessageOut
from app.schemas.common import decode_cursor, encode_cursor
from app.services import attachments as att
from app.services import chat_memory
from app.services.addressing import owner_address_instruction
from app.services.attachments import Shown
from app.services.audit import AuditService
from app.services.chat_handoff import HANDOFF_INSTRUCTION, Handoff
from app.services.chat_stream import ChatStreamManager, StreamState
from app.services.files import FileStore, Received
from app.services.images import ImageNotUsable, image_size, make_model_copy
from app.tasks.queue import TaskEnqueuer

DEFAULT_TITLE = "New chat"


# A message the owner sent while an answer was being written: answered right after it.
QUEUED = "queued"


class GenerationInProgress(Conflict):
    code = "generation_in_progress"
    message = "Wait for the current answer to finish (or stop it) before sending another message."


class InvalidAttachment(AppError):
    status_code = 422
    code = "invalid_attachment"
    message = "This file cannot be attached."


async def chat_system_prompt(
    db: AsyncSession, user_id: uuid.UUID, *, hand_off: bool = False
) -> str | None:
    """The chat's instructions: the owner's form of address, and — when the chat may hand
    work to the agents — when to do so (none = no system prompt). History and attachments
    stay in the messages, fenced as data."""
    parts = [await owner_address_instruction(db, user_id), HANDOFF_INSTRUCTION if hand_off else ""]
    return "\n\n".join(p for p in parts if p) or None


def make_title(content: str, max_chars: int) -> str:
    line = " ".join(content.split())
    return line if len(line) <= max_chars else line[: max_chars - 1].rstrip() + "…"


def _chunks[T](items: Sequence[T], size: int = 5000) -> list[Sequence[T]]:
    """Long id lists are queried in parts (PostgreSQL takes at most 32767 parameters)."""
    return [items[i : i + size] for i in range(0, len(items), size)]


def _viewable(a: Attachment) -> bool:
    """A picture the model can be shown: an old row with its bytes, or a prepared file."""
    return a.kind == att.IMAGE and (a.model_path is not None if a.storage_path else True)


def _read_or_none(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _remove_with_copies(path: Path) -> None:
    for item in path.parent.glob(f"{path.name}*"):
        item.unlink(missing_ok=True)


class ChatService:
    def __init__(self, db: AsyncSession, settings: Settings, gateway: ModelGateway) -> None:
        self.db = db
        self.settings = settings
        self.gateway = gateway
        self.audit = AuditService(db)
        self.store = FileStore(settings)

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
        await asyncio.to_thread(self.store.remove_chat, conversation_id)  # its files

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

    async def _history(
        self, conversation_id: uuid.UUID, after: tuple[datetime, uuid.UUID] | None = None
    ) -> list[Message]:
        """The latest completed messages; with a summary only those after it (the summary
        covers the older ones — services/chat_memory.py)."""
        query = select(Message).where(
            Message.conversation_id == conversation_id,
            Message.status == "completed",
            Message.role.in_(("user", "assistant")),
        )
        if after is not None:
            query = query.where(chat_memory.after_cursor(after))
        rows = (
            await self.db.execute(
                query.order_by(Message.created_at.desc(), Message.id.desc()).limit(
                    self.settings.chat_context_max_messages - 1
                )
            )
        ).scalars()
        return list(reversed(list(rows)))

    async def attachments_by_message(
        self, ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[Attachment]]:
        out: dict[uuid.UUID, list[Attachment]] = {}
        for chunk in _chunks(ids):
            rows = await self.db.execute(
                select(Attachment)
                .where(Attachment.message_id.in_(chunk))
                .order_by(Attachment.created_at)
            )
            for a in rows.scalars():
                assert a.message_id is not None
                out.setdefault(a.message_id, []).append(a)
        return out

    # --- attachments -------------------------------------------------------------------

    def upload_folder(self, conversation_id: uuid.UUID) -> Path:
        return self.store.chat_dir(conversation_id)

    async def store_upload(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, received: Received
    ) -> Attachment:
        """Keep an uploaded file (already streamed to disk) and prepare it for the model."""
        attachment_id = uuid.uuid4()
        final = received.path.with_name(str(attachment_id))
        try:
            await self.get(user_id, conversation_id)
            await asyncio.to_thread(os.replace, received.path, final)
            attachment = await self._describe(attachment_id, final, received)
            attachment.user_id = user_id
            attachment.conversation_id = conversation_id
            self.db.add(attachment)
            await self.db.commit()
        except BaseException:
            await asyncio.to_thread(received.path.unlink, missing_ok=True)
            await asyncio.to_thread(_remove_with_copies, final)
            raise
        return attachment

    async def _describe(self, attachment_id: uuid.UUID, path: Path, r: Received) -> Attachment:
        """What the file is (from its bytes, not its name or the client's claim)."""
        settings = self.settings
        sniffed = att.sniff(r.head)
        text, text_chars, note, pages = "", None, None, None
        model_path: str | None = None
        if sniffed and sniffed[0] == att.IMAGE:
            kind, media = sniffed
            model_path, note = await self._model_view(path, media, r)
        elif sniffed and sniffed[0] == att.PDF:
            kind, media = sniffed
            pdf = await asyncio.to_thread(
                att.extract_pdf_text,
                path,
                settings.chat_pdf_max_pages,
                settings.chat_attachment_text_max_chars,
                settings.chat_pdf_timeout_seconds,
            )
            text, text_chars, note, pages = pdf.text, pdf.chars, pdf.note, pdf.pages
        elif r.text.is_text:
            kind, text, text_chars = att.TEXT, r.text.text, r.text.chars
            media = att.clean_media_type(r.content_type) or "text/plain"
        else:
            kind = att.FILE
            media = (
                att.clean_media_type(r.content_type)
                or mimetypes.guess_type(r.filename)[0]
                or "application/octet-stream"
            )
        return Attachment(
            id=attachment_id,
            message_id=None,
            filename=r.filename,
            content_type=media,
            size=r.size,
            sha256=r.sha256,
            text=text,
            kind=kind,
            pages=pages,
            storage_path=self.store.relative(path),
            model_path=model_path,
            text_chars=text_chars,
            note=note,
        )

    async def _model_view(
        self, path: Path, media: str, r: Received
    ) -> tuple[str | None, str | None]:
        """(file the model is shown, note): the original if it fits, else a smaller copy."""
        settings = self.settings
        size = image_size(r.head, media)
        if size and size[0] * size[1] > settings.chat_image_max_pixels:
            return None, f"it is too large to process ({size[0]}x{size[1]} pixels)"
        fits = (
            size is not None
            and max(size) <= settings.chat_image_model_max_side
            and r.size <= settings.chat_image_model_max_bytes
        )
        if fits:
            return self.store.relative(path), None
        try:
            copy = await make_model_copy(path, Path(f"{path}.model"), media, settings)
        except ImageNotUsable as exc:
            return None, str(exc)
        return self.store.relative(copy.path), None

    async def attachment_content(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, attachment_id: uuid.UUID
    ) -> tuple[Attachment, Path | bytes]:
        """The original file: a path on disk, or the bytes of a row from before 0014a."""
        await self.get(user_id, conversation_id)
        a = await self.db.get(Attachment, attachment_id)
        if a is None or a.user_id != user_id or a.conversation_id != conversation_id:
            raise NotFound("File not found.")
        if a.storage_path:
            path = self.store.resolve(a.storage_path)
            if not await asyncio.to_thread(path.is_file):
                raise NotFound("The file is missing on the server's disk.")
            return a, path
        data, text = (
            await self.db.execute(
                select(Attachment.data, Attachment.text).where(Attachment.id == attachment_id)
            )
        ).one()
        return a, data if data is not None else text.encode("utf-8")

    async def _text_lengths(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        out: dict[uuid.UUID, int] = {}
        for chunk in _chunks(ids):
            rows = await self.db.execute(
                select(Attachment.id, func.length(Attachment.text)).where(Attachment.id.in_(chunk))
            )
            out.update({i: int(n or 0) for i, n in rows})
        return out

    async def _texts(self, allocation: dict[uuid.UUID, int]) -> dict[uuid.UUID, str]:
        """The first n characters of each file's text — only what the prompt uses."""
        wanted = [(i, n) for i, n in allocation.items() if n > 0]
        out: dict[uuid.UUID, str] = {}
        for chunk in _chunks(wanted, 2000):
            length = case(dict(chunk), value=Attachment.id, else_=0)
            rows = await self.db.execute(
                select(Attachment.id, func.left(Attachment.text, length)).where(
                    Attachment.id.in_([i for i, _ in chunk])
                )
            )
            out.update({i: t or "" for i, t in rows})
        return out

    async def _image_parts(self, images: list[Attachment]) -> dict[uuid.UUID, ImagePart]:
        out: dict[uuid.UUID, ImagePart] = {}
        old = [a.id for a in images if not a.storage_path]
        if old:
            rows = await self.db.execute(
                select(Attachment.id, Attachment.content_type, Attachment.data).where(
                    Attachment.id.in_(old)
                )
            )
            for i, media, data in rows:
                if data:
                    out[i] = ImagePart(media_type=media, data_b64=base64.b64encode(data).decode())
        for a in images:
            if not (a.storage_path and a.model_path):
                continue
            data = await asyncio.to_thread(_read_or_none, self.store.resolve(a.model_path))
            if data:
                sniffed = att.sniff(data[:16])
                media = sniffed[1] if sniffed else a.content_type
                out[a.id] = ImagePart(media_type=media, data_b64=base64.b64encode(data).decode())
        return out

    async def _for_model(
        self,
        history: list[Message],
        history_files: dict[uuid.UUID, list[Attachment]],
        files: list[Attachment],
        budget: int,
    ) -> tuple[list[ChatMessage], dict[uuid.UUID, Shown], dict[uuid.UUID, ImagePart]]:
        """What of every attachment the model sees: text within the character budget (the
        new message first, then older ones), pictures within the picture budget."""
        settings = self.settings
        newest_first = [files, *(history_files.get(m.id, []) for m in reversed(history))]
        text_ids = [a.id for group in newest_first for a in group if a.kind in att.TEXT_KINDS]
        lengths = await self._text_lengths(text_ids)
        allocation = att.allocate(
            [
                [(a.id, lengths.get(a.id, 0)) for a in group if a.kind in att.TEXT_KINDS]
                for group in newest_first
            ],
            budget,
        )
        texts = await self._texts(allocation)

        current = [a for a in files if _viewable(a)][: settings.chat_images_per_request]
        room = min(settings.chat_context_images, settings.chat_images_per_request) - len(current)
        past = [a for m in history for a in history_files.get(m.id, []) if _viewable(a)]
        parts = await self._image_parts([*current, *(past[-room:] if room > 0 else [])])

        shown: dict[uuid.UUID, Shown] = {}
        for group in newest_first:
            for a in group:
                if a.kind == att.IMAGE:
                    # A past picture that is no longer re-sent keeps its tag as it was sent.
                    sent_before = group is not files and _viewable(a)
                    state = "shown" if a.id in parts or sent_before else None
                    if state is None and _viewable(a):
                        state = "omitted"
                    shown[a.id] = Shown(image=state)
                else:
                    shown[a.id] = Shown(text=texts.get(a.id, ""), stored_chars=lengths.get(a.id, 0))
        messages = [
            ChatMessage(
                role=m.role,  # type: ignore[arg-type]
                content=att.with_attachments(m.content, history_files.get(m.id, []), shown),
                images=tuple(parts[a.id] for a in history_files.get(m.id, []) if a.id in parts),
            )
            for m in history
        ]
        return messages, shown, parts

    async def _pending_files(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, attachment_ids: list[uuid.UUID]
    ) -> list[Attachment]:
        ids = list(dict.fromkeys(attachment_ids))
        limit = self.settings.chat_attachments_per_message
        if limit and len(ids) > limit:
            raise InvalidAttachment(f"At most {limit} files per message.")
        files: list[Attachment] = []
        for chunk in _chunks(ids):
            files += (
                await self.db.execute(
                    select(Attachment).where(
                        Attachment.id.in_(chunk),
                        Attachment.user_id == user_id,
                        Attachment.conversation_id == conversation_id,
                        Attachment.message_id.is_(None),
                    )
                )
            ).scalars()
        if len(files) != len(ids):
            raise InvalidAttachment("An attached file is missing or was already sent.")
        order = {i: n for n, i in enumerate(ids)}
        return sorted(files, key=lambda a: (a.created_at, order[a.id]))

    async def send(
        self,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        content: str,
        model_config_id: uuid.UUID | None,
        streams: ChatStreamManager,
        attachment_ids: list[uuid.UUID] | None = None,
        queue: TaskEnqueuer | None = None,
    ) -> tuple[Message, Message | None, StreamState | None]:
        """Send a message. While an answer is being written the message waits in line
        (owner: several messages in a row — status ``queued``) and is answered by itself
        right after it (``answer_next``); then the assistant message and stream are None."""
        # Row lock: two concurrent sends to one conversation are serialised here.
        conv = await self._lock_conversation(user_id, conversation_id)
        files = (
            await self._pending_files(user_id, conversation_id, attachment_ids)
            if attachment_ids
            else []
        )
        now = datetime.now(UTC)
        if await self._busy(conversation_id):
            waiting = Message(
                conversation_id=conversation_id,
                user_id=user_id,
                role="user",
                content=content,
                status=QUEUED,
                model_config_id=model_config_id,
                created_at=now,
            )
            self.db.add(waiting)
            await self.db.flush()
            for attachment in files:
                attachment.message_id = waiting.id
            conv.last_message_at = now
            await bus.emit(
                self.db,
                user_id=user_id,
                type="chat.message_completed",
                payload={
                    "conversation_id": str(conversation_id),
                    "message": MessageOut.model_validate(waiting).model_dump(mode="json"),
                },
            )
            await bus.commit(self.db)
            return waiting, None, None

        target = await self.gateway.resolve(
            self.db, user_id, model_config_id or conv.model_config_id
        )
        from app.services.usage import ensure_within_budget

        await ensure_within_budget(self.db, user_id)
        user_msg = Message(
            conversation_id=conversation_id,
            user_id=user_id,
            role="user",
            content=content,
            status="completed",
            created_at=now,
            completed_at=now,
        )
        assistant_msg, state = await self._start_answer(
            conv, user_msg, files, target, model_config_id, streams, queue
        )
        return user_msg, assistant_msg, state

    async def answer_next(
        self,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        streams: ChatStreamManager,
        queue: TaskEnqueuer | None,
    ) -> StreamState | None:
        """The oldest message waiting in line gets its answer (after the previous one ended).
        If it cannot be answered now (no model, budget used up) the answer fails with the
        reason, as a direct send would have said."""
        conv = await self._lock_conversation(user_id, conversation_id)
        if await self._busy(conversation_id):
            return None
        waiting = (
            await self.db.execute(
                select(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.role == "user",
                    Message.status == QUEUED,
                )
                .order_by(Message.created_at, Message.id)
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if waiting is None:
            return None
        requested = waiting.model_config_id
        files = (await self.attachments_by_message([waiting.id])).get(waiting.id, [])
        now = datetime.now(UTC)
        try:
            target = await self.gateway.resolve(self.db, user_id, requested or conv.model_config_id)
            from app.services.usage import ensure_within_budget

            await ensure_within_budget(self.db, user_id)
        except AppError as exc:
            waiting.status, waiting.completed_at = "completed", now
            failed = Message(
                conversation_id=conversation_id,
                user_id=user_id,
                role="assistant",
                content="",
                status="failed",
                error_code=exc.code,
                error_message=exc.message,
                created_at=now,
                completed_at=now,
            )
            self.db.add(failed)
            await self.db.flush()
            await bus.emit(
                self.db,
                user_id=user_id,
                type="chat.message_completed",
                payload={
                    "conversation_id": str(conversation_id),
                    "message": MessageOut.model_validate(failed).model_dump(mode="json"),
                },
            )
            await bus.commit(self.db)
            return None
        waiting.status, waiting.completed_at, waiting.model_config_id = "completed", now, None
        _, state = await self._start_answer(conv, waiting, files, target, requested, streams, queue)
        return state

    async def _lock_conversation(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Conversation:
        conv = (
            await self.db.execute(
                select(Conversation).where(Conversation.id == conversation_id).with_for_update()
            )
        ).scalar_one_or_none()
        if conv is None or conv.user_id != user_id:
            raise NotFound("Conversation not found.")
        return conv

    async def _busy(self, conversation_id: uuid.UUID) -> bool:
        row = await self.db.execute(
            select(Message.id)
            .where(Message.conversation_id == conversation_id, Message.status == "streaming")
            .limit(1)
        )
        return row.first() is not None

    async def _start_answer(
        self,
        conv: Conversation,
        user_msg: Message,
        files: list[Attachment],
        target: ModelTarget,
        model_config_id: uuid.UUID | None,
        streams: ChatStreamManager,
        queue: TaskEnqueuer | None,
    ) -> tuple[Message, StreamState]:
        """Answer one owner message (new, or the next in line): history, recall and memory,
        then the stream. Commits."""
        user_id, conversation_id, content = conv.user_id, conv.id, user_msg.content
        cursor = chat_memory.summary_cursor(conv, self.settings)
        history_messages = [
            m for m in await self._history(conversation_id, cursor) if m.id != user_msg.id
        ]
        history_files = await self.attachments_by_message(
            [m.id for m in history_messages if m.role == "user"]
        )
        history, shown, parts = await self._for_model(
            history_messages,
            history_files,
            files,
            att.prompt_budget(self.settings, target.params),
        )
        # Earlier chats, tasks and memory (time-boxed; nothing when off or nothing found).
        recalled = await chat_memory.recall(
            self.db.bind,  # type: ignore[arg-type]
            self.gateway,
            self.settings,
            user_id,
            conversation_id,
            content,
        )
        recall_text, recall_used = chat_memory.recall_block(
            recalled, self.settings.chat_recall_max_chars
        )

        now = datetime.now(UTC)
        assistant_msg = Message(
            conversation_id=conversation_id,
            user_id=user_id,
            role="assistant",
            content="",
            status="streaming",
            model_config_id=target.model_config_id,
            provider_kind=target.provider_kind,
            model=target.model,
            # right after its own question: an answer from the line stays next to it in the
            # chat, before the messages sent after it
            created_at=user_msg.created_at + timedelta(microseconds=1),
            recalled_sources=[r.public() for r in recall_used] or None,
        )
        if user_msg.id is None:
            self.db.add(user_msg)
        self.db.add(assistant_msg)
        await self.db.flush()
        for attachment in files:
            attachment.message_id = user_msg.id
        if conv.title == DEFAULT_TITLE and not history:
            conv.title = make_title(content, self.settings.chat_title_max_chars)
        if model_config_id is not None:
            conv.model_config_id = model_config_id
        conv.last_message_at = now
        await self.db.commit()

        # Work goes to the agents by itself (not with files: the agents do not see them).
        hand_off = self.settings.chat_auto_handoff and queue is not None and not files
        request = ChatRequest(
            model=target.model,
            messages=(
                *history,
                ChatMessage(
                    role="user",
                    content=att.with_attachments(content, files, shown),
                    images=tuple(parts[a.id] for a in files if a.id in parts),
                ),
            ),
            # Instructions first, then data: what it always knows about the owner (pinned
            # memory), the summary of older messages, then recall.
            system=chat_memory.chat_system(
                await chat_system_prompt(self.db, user_id, hand_off=hand_off),
                await build_owner_context(self.db, user_id, self.settings),
                chat_memory.summary_block(conv.summary or "") if cursor else "",
                recall_text,
            ),
        )
        state = streams.start(
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=assistant_msg.id,
            target=target,
            request=request,
            handoff=(
                Handoff(queue, content, self.settings.chat_title_max_chars) if hand_off else None
            ),
        )
        return assistant_msg, state
