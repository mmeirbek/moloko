"""``memory_save``: the agent writes a note to its own memory (spec 17). ``write`` category,
so a supervised agent needs approval. Saved as data like any memory, ``created_by=agent``."""

from __future__ import annotations

from typing import Any

from app.agents.state import AgentType, MemoryType
from app.models.memory import Memory, MemoryRevision
from app.services.audit import AuditService
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


class MemorySave(BaseTool):
    name = "memory_save"
    title = "Remember"
    description = (
        "Save a short note to your own memory for future tasks (facts, preferences, decisions)."
    )
    group = "memory"
    category = ToolCategory.WRITE
    input_schema = object_schema(
        {
            "title": string_prop("Short title", maxLength=200),
            "content": string_prop("What to remember"),
        },
        ["title", "content"],
    )

    async def check_scope(self, ctx: ToolContext, args: dict[str, Any]) -> None:
        if ctx.agent.agent_type == AgentType.SUBAGENT.value:
            raise ScopeError("subagents have no memory of their own")
        if len(args["content"]) > ctx.settings.memory_entry_max_chars:
            raise ScopeError(f"at most {ctx.settings.memory_entry_max_chars} characters")

    def describe(self, args: dict[str, Any]) -> OperationInfo:
        return OperationInfo(
            summary=f"Remember: {args['title']}",
            resources=["agent memory"],
            consequences="The note is added to this agent's memory and used in its future tasks.",
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        async with ctx.sessionmaker() as db:
            memory = Memory(
                user_id=ctx.user_id,
                agent_id=ctx.agent.id,
                memory_type=MemoryType.AGENT.value,
                title=args["title"].strip()[:200],
                content=args["content"].strip(),
                revision=1,
                created_by="agent",
            )
            db.add(memory)
            await db.flush()
            db.add(
                MemoryRevision(
                    memory_id=memory.id,
                    user_id=ctx.user_id,
                    revision=1,
                    memory_type=memory.memory_type,
                    agent_id=memory.agent_id,
                    project=None,
                    title=memory.title,
                    content=memory.content,
                    pinned=False,
                    changed_by="agent",
                )
            )
            await AuditService(db).record(
                "memory.created",
                "success",
                actor_type="agent",
                actor_id=ctx.agent.id,
                user_id=ctx.user_id,
                resource_type="memory",
                resource_id=str(memory.id),
                details={"type": memory.memory_type, "agent_id": str(ctx.agent.id)},
            )
            await db.commit()
        return ToolOutput(f"Saved to memory: {args['title']}")


MEMORY_TOOLS: tuple[BaseTool, ...] = (MemorySave(),)
