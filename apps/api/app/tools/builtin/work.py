"""The office's work history for agents (owner request: agents can always check what was
done — their own work, other agents' and subagents' work, and the owner's chats).

* ``work_search`` (read) — find finished tasks, agent↔agent messages and chat messages by
  words or meaning, with source type, title, date, agent, a snippet and ids.
* ``work_read`` (read) — the full record of one task (request, result, error, subtasks,
  agent messages, tool calls by name and status, files), one message, or a chat (paged).

Both are read-only, owner-scoped, and always allowed for every agent (``ALWAYS_ALLOWED`` in
``app/tools/policy.py``); the owner can switch them off or block them per agent. Everything
they return is fenced as untrusted data.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.memory import work
from app.memory.context import RECORDS_HEADER, fence_record
from app.tools.base import (
    BaseTool,
    OperationInfo,
    ScopeError,
    ToolCategory,
    ToolContext,
    ToolOutput,
    object_schema,
    string_prop,
)

SCOPES = {
    "mine": ("task", "agent_message"),
    "all_agents": ("task", "agent_message"),
    "chats": ("chat_message",),
    "everything": ("task", "agent_message", "chat_message"),
}
ID_PROP = {"type": "string", "maxLength": 64}


class WorkSearch(BaseTool):
    name = "work_search"
    title = "Search work history"
    description = (
        "Search the office's work history: finished tasks of all agents (with their results "
        "and errors), messages between agents, and the owner's chats. scope: 'mine' = your "
        "own tasks and messages, 'all_agents' = every agent's tasks and messages, 'chats' = "
        "the owner's chats, 'everything' (default) = all of it. Returns matches with ids; "
        "read one in full with work_read."
    )
    group = "history"
    category = ToolCategory.READ
    input_schema = object_schema(
        {
            "query": string_prop("What to look for", maxLength=500),
            "scope": {
                "type": "string",
                "enum": list(SCOPES),
                "description": "Where to look (default: everything)",
            },
            "agent": string_prop(
                "Only the work of this agent (name or id); not with scope 'mine' or 'chats'",
                maxLength=200,
            ),
            "since": string_prop("Only work from this date on (YYYY-MM-DD)", maxLength=40),
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        },
        ["query"],
    )

    async def check_scope(self, ctx: ToolContext, args: dict[str, Any]) -> None:
        if not args["query"].strip():
            raise ScopeError("empty query")
        try:
            work.parse_since(args.get("since"))
        except ValueError:
            raise ScopeError("'since' must be a date like 2026-11-02") from None
        if args.get("agent", "").strip():
            async with ctx.sessionmaker() as db:
                if not await work.find_agents(db, ctx.user_id, args["agent"]):
                    raise ScopeError(f"there is no agent named '{args['agent']}'")

    def describe(self, args: dict[str, Any]) -> OperationInfo:
        return OperationInfo(
            summary=f"Search work history: {args['query'][:80]}",
            resources=["tasks", "agent messages", "chats"],
            consequences="Read-only.",
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        from app.providers.gateway import ModelGateway
        from app.search.query import Scope, search

        scope_name = args.get("scope") or "everything"
        types = SCOPES[scope_name]
        agent_ids: tuple[uuid.UUID, ...] | None = None
        async with ctx.sessionmaker() as db:
            if scope_name == "mine":
                agent_ids = (ctx.agent.id,)
            elif args.get("agent", "").strip() and scope_name != "chats":
                agent_ids = tuple(await work.find_agents(db, ctx.user_id, args["agent"]))
                types = tuple(t for t in types if t != "chat_message")
            scope = Scope(
                types=types, work_agent_ids=agent_ids, since=work.parse_since(args.get("since"))
            )
            hits = await search(
                db,
                ModelGateway(ctx.settings),
                ctx.settings,
                ctx.user_id,
                args["query"],
                scope=scope,
                limit=args.get("limit", 8),
            )
        if not hits:
            return ToolOutput("Nothing found in the work history.")
        parts = [RECORDS_HEADER]
        for h in hits:
            meta = h.meta
            attrs: dict[str, object] = {
                "title": h.title,
                "date": h.source_at.date().isoformat() if h.source_at else None,
            }
            if h.source_type == "task":
                attrs |= {
                    "task_id": h.source_id,
                    "agent": meta.get("agent_name"),
                    "status": meta.get("status"),
                    "run_id": h.run_id,
                }
            elif h.source_type == "agent_message":
                attrs |= {
                    "message_id": h.source_id,
                    "from": meta.get("agent_name"),
                    "to": meta.get("peer_agent_name"),
                    "message_type": meta.get("message_type"),
                    "task_id": meta.get("task_id"),
                    "run_id": h.run_id,
                }
            else:
                attrs |= {
                    "message_id": h.source_id,
                    "conversation_id": h.conversation_id,
                    "role": meta.get("role"),
                }
            attrs["score"] = h.score
            parts.append(fence_record(h.source_type, attrs, h.snippet))
        parts.append(
            "Read a record in full with work_read (task_id, message_id or conversation_id)."
        )
        return ToolOutput("\n\n".join(parts))


class WorkRead(BaseTool):
    name = "work_read"
    title = "Read a work record"
    description = (
        "Read one record of the work history in full. Give exactly one of: task_id (the "
        "request, result or error, subtasks with outcomes, agent messages, tool calls, "
        "files), message_id (a message between agents or a chat message), or "
        "conversation_id (the chat's messages; page with offset and limit)."
    )
    group = "history"
    category = ToolCategory.READ
    input_schema = object_schema(
        {
            "task_id": {**ID_PROP, "description": "A task id"},
            "message_id": {**ID_PROP, "description": "An agent message or chat message id"},
            "conversation_id": {**ID_PROP, "description": "A chat id"},
            "offset": {"type": "integer", "minimum": 0, "description": "Chat: skip messages"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        },
        [],
    )

    async def check_scope(self, ctx: ToolContext, args: dict[str, Any]) -> None:
        given = [k for k in ("task_id", "message_id", "conversation_id") if args.get(k)]
        if len(given) != 1:
            raise ScopeError("give exactly one of task_id, message_id, conversation_id")
        if work.as_uuid(args[given[0]]) is None:
            raise ScopeError(f"{given[0]} is not a valid id")

    def describe(self, args: dict[str, Any]) -> OperationInfo:
        ref = next(
            (f"{k} {args[k]}" for k in ("task_id", "message_id", "conversation_id") if args.get(k)),
            "",
        )
        return OperationInfo(summary=f"Read a work record: {ref}", consequences="Read-only.")

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        async with ctx.sessionmaker() as db:
            if args.get("task_id"):
                task_id = work.as_uuid(args["task_id"])
                assert task_id is not None
                text = await work.read_task(db, ctx.settings, ctx.user_id, task_id)
            elif args.get("message_id"):
                message_id = work.as_uuid(args["message_id"])
                assert message_id is not None
                text = await work.read_message(db, ctx.settings, ctx.user_id, message_id)
            else:
                conversation_id = work.as_uuid(args["conversation_id"])
                assert conversation_id is not None
                text = await work.read_conversation(
                    db,
                    ctx.settings,
                    ctx.user_id,
                    conversation_id,
                    int(args.get("offset", 0)),
                    int(args.get("limit", 30)),
                )
        if text is None:
            return ToolOutput("There is no such record.", is_error=True)
        return ToolOutput(text)


WORK_TOOLS: tuple[BaseTool, ...] = (WorkSearch(), WorkRead())
