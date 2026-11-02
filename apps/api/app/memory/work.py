"""The office's work history as agents read it (owner request: agents can always check
what was done, by whom, and how it ended).

Everything here is scoped to one owner and returned fenced as untrusted data
(``fence_record``). Tool calls are summarised by name and status only — never their
arguments or results, which may hold secrets or private content.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import Settings
from app.memory.context import RECORDS_HEADER, fence_record
from app.models.agent import Agent
from app.models.agent_message import AgentMessage
from app.models.chat import Conversation, Message
from app.models.task import Task
from app.models.tooling import ToolCall, Workspace, WorkspaceFile

MAX_SUBTASKS = 30
MAX_MESSAGES = 30
MAX_TOOL_CALLS = 60
MAX_FILES = 100
EXCERPT = 300


def _day(value: datetime | None) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC") if value else ""


def _short(text: str, size: int = EXCERPT) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= size else text[: size - 1].rstrip() + "…"


def as_uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def parse_since(value: str | None) -> datetime | None:
    """``YYYY-MM-DD`` (or a full ISO date-time) → an aware datetime. ValueError if invalid."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        parsed = datetime.combine(date.fromisoformat(value.strip()[:10]), datetime.min.time())
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def find_agents(db: AsyncSession, user_id: uuid.UUID, ref: str) -> list[uuid.UUID]:
    """The owner's agents (archived and subagents included) matching a name or an id."""
    ref = ref.strip()
    by_id = as_uuid(ref)
    if by_id is not None:
        found = await db.execute(
            select(Agent.id).where(Agent.user_id == user_id, Agent.id == by_id)
        )
        return list(found.scalars())
    exact = await db.execute(
        select(Agent.id).where(Agent.user_id == user_id, func.lower(Agent.name) == ref.lower())
    )
    ids = list(exact.scalars())
    if ids:
        return ids
    like = ref.replace("%", "").replace("_", "")
    partial = await db.execute(
        select(Agent.id).where(Agent.user_id == user_id, Agent.name.ilike(f"%{like}%")).limit(50)
    )
    return list(partial.scalars()) if like else []


async def _names(db: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = await db.execute(select(Agent.id, Agent.name).where(Agent.id.in_(wanted)))
    return {i: n for i, n in rows.all()}


async def read_task(
    db: AsyncSession, settings: Settings, user_id: uuid.UUID, task_id: uuid.UUID
) -> str | None:
    task = await db.get(Task, task_id)
    if task is None or task.user_id != user_id:
        return None
    children = list(
        (
            await db.execute(
                select(Task)
                .where(Task.user_id == user_id, Task.parent_task_id == task.id)
                .order_by(Task.created_at, Task.id)
                .limit(MAX_SUBTASKS)
            )
        ).scalars()
    )
    message_scope = AgentMessage.task_id == task.id
    if task.parent_task_id is None and task.run_id is not None:
        message_scope = or_(message_scope, AgentMessage.run_id == task.run_id)
    messages = list(
        (
            await db.execute(
                select(AgentMessage)
                .where(AgentMessage.user_id == user_id, message_scope)
                .order_by(AgentMessage.created_at)
                .limit(MAX_MESSAGES)
            )
        ).scalars()
    )
    calls = (
        await db.execute(
            select(ToolCall.step, ToolCall.tool_name, ToolCall.status)
            .where(ToolCall.user_id == user_id, ToolCall.task_id == task.id)
            .order_by(ToolCall.created_at)
            .limit(MAX_TOOL_CALLS)
        )
    ).all()
    files = (
        await db.execute(
            select(WorkspaceFile.path, WorkspaceFile.size, Workspace.name, Workspace.cleaned_at)
            .join(Workspace, Workspace.id == WorkspaceFile.workspace_id)
            .where(
                Workspace.user_id == user_id,
                WorkspaceFile.deleted.is_(False),
                or_(WorkspaceFile.last_task_id == task.id, Workspace.task_id == task.id),
            )
            .order_by(WorkspaceFile.path)
            .limit(MAX_FILES)
        )
    ).all()
    names = await _names(
        db,
        {task.agent_id, *(c.agent_id for c in children)}
        | {m.sender_agent_id for m in messages}
        | {m.receiver_agent_id for m in messages},
    )

    budget = max(1000, settings.tool_output_max_chars // 2)
    body = []
    if task.description.strip():
        body.append("Request:\n" + task.description.strip()[:budget])
    if (task.result or "").strip():
        body.append("Result:\n" + (task.result or "").strip()[:budget])
    if task.error_code or task.error_message:
        body.append(f"Error: {task.error_code or ''} {task.error_message or ''}".strip())
    parts = [
        RECORDS_HEADER,
        fence_record(
            "task",
            {
                "task_id": task.id,
                "title": task.title,
                "agent": names.get(task.agent_id) if task.agent_id else None,
                "status": task.status,
                "task_type": task.task_type,
                "run_id": task.run_id,
                "parent_task_id": task.parent_task_id,
                "created": _day(task.created_at),
                "finished": _day(task.completed_at),
            },
            "\n\n".join(body) or "(no request text)",
        ),
    ]
    if children:
        lines = []
        for c in children:
            outcome = c.result if c.status == "completed" else (c.error_message or c.error_code)
            lines.append(
                f"- [{c.status}] {c.title} — {names.get(c.agent_id) if c.agent_id else '?'} "
                f"(task {c.id}): {_short(outcome or '')}"
            )
        parts.append(fence_record("subtasks", {"count": len(children)}, "\n".join(lines)))
    if messages:
        lines = [
            f"- {_day(m.created_at)} {names.get(m.sender_agent_id, '?')} → "
            f"{names.get(m.receiver_agent_id, '?')} ({m.message_type}, {m.status}, "
            f"message {m.id}): {_short(str((m.content or {}).get('summary') or ''))}"
            for m in messages
        ]
        parts.append(fence_record("agent_messages", {"count": len(messages)}, "\n".join(lines)))
    if calls:
        lines = [f"- step {step}: {name} — {status}" for step, name, status in calls]
        parts.append(fence_record("tool_calls", {"count": len(calls)}, "\n".join(lines)))
    if files:
        lines = [
            f"- {path} ({size} bytes, workspace {ws}{', files removed' if cleaned else ''})"
            for path, size, ws, cleaned in files
        ]
        parts.append(fence_record("files", {"count": len(files)}, "\n".join(lines)))
    return "\n\n".join(parts)


async def read_conversation(
    db: AsyncSession,
    settings: Settings,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    offset: int,
    limit: int,
) -> str | None:
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user_id:
        return None
    total = (
        await db.execute(
            select(func.count()).select_from(Message).where(Message.conversation_id == conv.id)
        )
    ).scalar_one()
    rows = list(
        (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == conv.id)
                .order_by(Message.created_at, Message.id)
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
    )
    per_message = max(500, settings.tool_output_max_chars // max(1, len(rows)) - 200)
    parts = [
        RECORDS_HEADER,
        f'Chat "{_short(conv.title, 200)}": messages {offset + 1} to {offset + len(rows)} '
        f"of {total}"
        + (
            f" (more: work_read with conversation_id and offset={offset + len(rows)})"
            if offset + len(rows) < total
            else ""
        ),
    ]
    for m in rows:
        text = m.content if m.status == "completed" else (m.error_message or m.status)
        parts.append(
            fence_record(
                "chat_message",
                {
                    "message_id": m.id,
                    "role": m.role,
                    "date": _day(m.created_at),
                    "status": m.status,
                },
                (text or "")[:per_message],
            )
        )
    return "\n\n".join(parts)


async def read_message(
    db: AsyncSession, settings: Settings, user_id: uuid.UUID, message_id: uuid.UUID
) -> str | None:
    """An agent↔agent message, or a chat message with its place in the chat."""
    sender, receiver = aliased(Agent), aliased(Agent)
    row = (
        await db.execute(
            select(AgentMessage, sender.name, receiver.name)
            .outerjoin(sender, sender.id == AgentMessage.sender_agent_id)
            .outerjoin(receiver, receiver.id == AgentMessage.receiver_agent_id)
            .where(AgentMessage.user_id == user_id, AgentMessage.id == message_id)
        )
    ).one_or_none()
    budget = max(1000, settings.tool_output_max_chars - 1000)
    if row is not None:
        m, from_name, to_name = row
        content = m.content or {}
        body = [str(content.get("summary") or "")]
        if content.get("result"):
            body.append(str(content["result"]))
        body += [f"Note: {n}" for n in content.get("notes") or []]
        body += [
            f"File: {a.get('path')}" for a in content.get("artifacts") or [] if isinstance(a, dict)
        ]
        return "\n\n".join(
            [
                RECORDS_HEADER,
                fence_record(
                    "agent_message",
                    {
                        "message_id": m.id,
                        "from": from_name,
                        "to": to_name,
                        "message_type": m.message_type,
                        "status": m.status,
                        "task_id": m.task_id,
                        "run_id": m.run_id,
                        "date": _day(m.created_at),
                    },
                    "\n\n".join(p for p in body if p)[:budget],
                ),
            ]
        )
    chat = (
        await db.execute(
            select(Message, Conversation.title)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Message.user_id == user_id, Message.id == message_id)
        )
    ).one_or_none()
    if chat is None:
        return None
    msg, title = chat
    position = (
        await db.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id == msg.conversation_id, Message.created_at < msg.created_at
            )
        )
    ).scalar_one()
    text = msg.content if msg.status == "completed" else (msg.error_message or msg.status)
    return "\n\n".join(
        [
            RECORDS_HEADER,
            fence_record(
                "chat_message",
                {
                    "message_id": msg.id,
                    "conversation_id": msg.conversation_id,
                    "chat": title,
                    "role": msg.role,
                    "date": _day(msg.created_at),
                    "status": msg.status,
                },
                (text or "")[:budget],
            ),
            f"The whole chat: work_read with conversation_id={msg.conversation_id} "
            f"(this message is number {position + 1}; offset={max(0, position - 5)} reads "
            "around it).",
        ]
    )
