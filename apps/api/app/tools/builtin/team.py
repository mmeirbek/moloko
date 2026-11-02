"""Talking to colleagues directly, without the Orchestrator (owner request).

* ``agents_list`` (read) — who this agent may contact, with free / busy.
* ``agent_ask`` (write) — ask a colleague and wait for the answer: the colleague gets a
  task; this run stops without holding a worker and continues with the answer.
* ``agent_tell`` (write) — a one-way note (with workspace files) for the colleague's next run.

Who may talk to whom, the limits and the waiting mechanics live in ``app/agents/team.py``.
The scope check refuses a contact the rules do not allow (stored as a ``refused`` message and
audited) before any approval is asked for.
"""

from __future__ import annotations

from typing import Any

from app.agents import team
from app.agents.engine import agent_is_busy
from app.models.agent import Agent
from app.models.task import Task
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

AGENT_PROP = string_prop("The colleague's name (as agents_list shows it) or id", maxLength=200)
FILES_PROP = {
    "type": "array",
    "items": {"type": "string", "maxLength": 512},
    "description": "Files from your workspace to pass along (relative paths)",
}


class AgentsList(BaseTool):
    name = "agents_list"
    title = "Colleagues"
    description = (
        "List the colleagues (other agents of the owner) you may contact with agent_ask or "
        "agent_tell: name, role and whether they are free or busy right now."
    )
    group = "team"
    category = ToolCategory.READ
    input_schema = object_schema({}, [])

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        async with ctx.sessionmaker() as db:
            me = await db.get(Agent, ctx.agent.id)
            assert me is not None
            people = await team.colleagues(db, me)
        if not people:
            return ToolOutput("You have no colleagues you may contact.")
        lines = ["Colleagues you may contact:"]
        for a in people:
            role = " · ".join(p for p in (a.specialization or "", a.description.strip()) if p)
            state = "busy" if agent_is_busy(a) else "free"
            lines.append(f"- {a.name}{f' — {role}' if role else ''} ({state})")
        lines.append(
            "agent_ask waits for an answer (a busy colleague answers when free); "
            "agent_tell leaves a note for their next task."
        )
        return ToolOutput("\n".join(lines))


async def _receiver(ctx: ToolContext, ref: str, message_type: str) -> Agent:
    """The colleague, or ScopeError (a refused contact is stored and audited)."""
    async with ctx.sessionmaker() as db:
        me = await db.get(Agent, ctx.agent.id)
        assert me is not None
        receiver = await team.find_agent(db, me, ref)
        if receiver is None:
            raise ScopeError(f"there is no colleague named '{ref}' (see agents_list)")
        try:
            problem = team.contact_problem(me, receiver)
            if problem:
                raise team.Refused(problem)
            if message_type == "request":
                task = await db.get(Task, ctx.task_id)
                assert task is not None
                await team.check_ask(db, ctx.settings, me, task, receiver)
        except team.Refused as refused:
            await team.record_refusal(
                db,
                sender=me,
                receiver=receiver,
                code=refused.code,
                message_type=message_type,
                task_id=ctx.task_id,
                run_id=ctx.run_id,
            )
            await db.commit()
            raise ScopeError(refused.text) from None
        return receiver


async def _check_files(ctx: ToolContext, args: dict[str, Any]) -> None:
    paths = [str(p) for p in args.get("files") or []]
    if paths:
        team.file_refs(ctx.settings, await ctx.workspace(), paths)


class AgentAsk(BaseTool):
    name = "agent_ask"
    title = "Ask a colleague"
    description = (
        "Ask a colleague (another agent of the owner) a question or hand them a piece of "
        "work, and wait for their answer. They work on it as their own task, with their own "
        "tools and rules; you continue when the answer arrives (or with a note that none "
        "came in time). Use agents_list to see who you may ask."
    )
    group = "team"
    category = ToolCategory.WRITE
    input_schema = object_schema(
        {
            "agent": AGENT_PROP,
            "request": string_prop("What you need from them, self-contained", minLength=1),
            "context": string_prop("Background they need (optional)"),
            "files": FILES_PROP,
        },
        ["agent", "request"],
    )

    async def check_scope(self, ctx: ToolContext, args: dict[str, Any]) -> None:
        team.check_text(ctx.settings, "request", str(args["request"]))
        team.check_text(ctx.settings, "context", str(args.get("context") or ""))
        await _check_files(ctx, args)
        await _receiver(ctx, str(args["agent"]), "request")

    def describe(self, args: dict[str, Any]) -> OperationInfo:
        who = str(args.get("agent", ""))
        files = [f"workspace:{p}" for p in args.get("files") or []]
        return OperationInfo(
            summary=f"Ask agent {who}: {str(args.get('request', ''))[:300]}",
            resources=[f"agent:{who}", *files],
            consequences=(
                f"{who} gets a task with this request and works on it under its own rules, "
                "approvals and budget; this agent waits for the answer (with a time limit)."
            ),
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        return await team.ask(ctx, args)  # raises AwaitingAgent when the question is out


class AgentTell(BaseTool):
    name = "agent_tell"
    title = "Message a colleague"
    description = (
        "Send a colleague (another agent of the owner) a one-way note — a result, a hint, "
        "files from your workspace. They read it at the start of their next task; you do "
        "not wait for a reply."
    )
    group = "team"
    category = ToolCategory.WRITE
    input_schema = object_schema(
        {
            "agent": AGENT_PROP,
            "message": string_prop("The note", minLength=1),
            "files": FILES_PROP,
        },
        ["agent", "message"],
    )

    async def check_scope(self, ctx: ToolContext, args: dict[str, Any]) -> None:
        team.check_text(ctx.settings, "message", str(args["message"]))
        await _check_files(ctx, args)
        await _receiver(ctx, str(args["agent"]), "note")

    def describe(self, args: dict[str, Any]) -> OperationInfo:
        who = str(args.get("agent", ""))
        files = [f"workspace:{p}" for p in args.get("files") or []]
        return OperationInfo(
            summary=f"Message agent {who}: {str(args.get('message', ''))[:300]}",
            resources=[f"agent:{who}", *files],
            consequences=f"{who} reads this note (and gets copies of the files) at the start "
            "of its next task.",
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        return await team.tell(ctx, args)


TEAM_TOOLS: tuple[BaseTool, ...] = (AgentsList(), AgentAsk(), AgentTell())
