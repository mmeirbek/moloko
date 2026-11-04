"""A task run by Codex (owner's decision 2026-11-04: Codex with the ChatGPT sign-in, for coding):
when the run's model is a Codex model (provider kind ``codex``), the agent's task goes to the
`codex` service instead of moloko's own loop. Codex works in the task's workspace with its own
tools (commands, file edits) inside its container; moloko shows each of its steps in the task's
chat, keeps its usage, its thread (to go on with the owner's notes) and its final answer.

Codex acts inside the codex container — the isolation boundary — not through
app/tools/runner.py, so its actions are records here (``agent.codex_step``), not tool calls.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from app.agents.engine import lock_run, lock_task, raise_task_progress, step_progress
from app.codex.client import CodexClient
from app.events import bus
from app.models.agent import Agent
from app.providers.base import ProviderError, Usage
from app.services.workspaces import workspace_for_task

if TYPE_CHECKING:
    from app.runtimes.base import RunContext
    from app.runtimes.native import NativeRuntime, RunSetup

EXCERPT = 2000


def codex_prompt(system: str, task_prompt: str) -> str:
    """Codex has its own instructions; ours (role, memory fenced as data, the owner's address)
    go first in its prompt, then the task."""
    return (
        f"{system}\n\nYou work in the current folder: it is this task's workspace. Write in "
        f"the owner's language when you report.\n\n---\n\n{task_prompt}"
    )


def step_of(item: dict[str, Any]) -> dict[str, Any] | None:
    """What one finished Codex item shows in the task's chat (None: nothing to show)."""
    kind = item.get("type")
    if kind == "command_execution":
        code = item.get("exit_code")
        return {
            "kind": "command",
            "title": str(item.get("command", ""))[:300],
            "detail": str(item.get("aggregated_output", ""))[-EXCERPT:],
            "ok": code == 0,
            "exit_code": code,
        }
    if kind == "file_change":
        changes = item.get("changes") or []
        files = [f"{c.get('kind', '')} {c.get('path', '')}".strip() for c in changes][:50]
        return {
            "kind": "files",
            "title": ", ".join(files)[:300],
            "detail": "\n".join(files),
            "ok": item.get("status") != "failed",
        }
    if kind == "web_search":
        return {"kind": "search", "title": str(item.get("query", ""))[:300], "ok": True}
    if kind == "mcp_tool_call":
        return {
            "kind": "tool",
            "title": f"{item.get('server', '')}.{item.get('tool', '')}",
            "ok": item.get("status") != "failed",
        }
    if kind == "error":
        return {"kind": "error", "title": str(item.get("message", ""))[:300], "ok": False}
    return None


def failure(message: str) -> ProviderError:
    """Codex's own error, in the kinds the task's error shows."""
    low = message.lower()
    if "usage limit" in low or "rate limit" in low or "429" in low:
        return ProviderError("rate_limited", message[:300], provider="codex")
    if "login" in low or "401" in low or "unauthorized" in low or "sign in" in low:
        return ProviderError("auth_failed", message[:300], provider="codex")
    return ProviderError("unavailable", message[:300], provider="codex")


async def run_with_codex(
    runtime: NativeRuntime, ctx: RunContext, setup: RunSetup, system: str, prompt: str
) -> str:
    client = CodexClient(ctx.settings)
    async with ctx.sessionmaker() as db:
        workspace = await workspace_for_task(db, ctx.settings, ctx.task_id)
        await db.commit()
    thread_id: str | None = (setup.run.state or {}).get("codex_thread_id")
    steps = setup.steps
    final = ""
    text: str = codex_prompt(system, prompt)
    started = time.monotonic()
    while True:
        await runtime._ensure_working(ctx)
        completed = False
        exit_code: int | None = None
        stderr = ""
        async for event in client.run(
            cwd=str(workspace.id), prompt=text, model=setup.target.model, thread_id=thread_id
        ):
            await ctx.control.check()  # pause / stop: leaving the stream ends Codex
            kind = event.get("type")
            if kind == "thread.started" and event.get("thread_id"):
                thread_id = str(event["thread_id"])
                await _save(ctx, {"codex_thread_id": thread_id})
            elif kind == "item.completed" and isinstance(event.get("item"), dict):
                item = event["item"]
                if item.get("type") == "agent_message" and item.get("text"):
                    final = str(item["text"])
                    steps += 1
                    await _emit(
                        ctx, steps, "agent.message", {"step": steps, "text": final[:EXCERPT]}
                    )
                elif (shown := step_of(item)) is not None:
                    steps += 1
                    await _emit(ctx, steps, "agent.codex_step", {"step": steps, **shown})
            elif kind == "turn.completed":
                completed = True
                await _usage(ctx, setup, event.get("usage") or {})
            elif kind in ("turn.failed", "error"):
                error = event.get("error") if kind == "turn.failed" else event
                raise failure(str((error or {}).get("message", "Codex failed")))
            elif kind == "moloko.exit":
                exit_code = int(event.get("code") or 0)
                stderr = str(event.get("stderr") or "")
        if not completed:
            raise failure(
                stderr.strip().splitlines()[-1] if stderr.strip() else f"Codex exited ({exit_code})"
            )
        # The owner wrote while Codex worked: it goes on in the same thread with the notes.
        notes = await _take_notes(ctx)
        if not notes:
            break
        text = notes
    await _save(ctx, {"elapsed_seconds": setup.elapsed + time.monotonic() - started})
    return final


async def _save(ctx: RunContext, values: dict[str, Any]) -> None:
    async with ctx.sessionmaker() as db:
        run = await lock_run(db, ctx.run_id)
        run.state = {**(run.state or {}), **values}
        await bus.commit(db)


async def _emit(ctx: RunContext, steps: int, kind: str, payload: dict[str, Any]) -> None:
    async with ctx.sessionmaker() as db:
        run = await lock_run(db, ctx.run_id)
        run.steps = steps
        task = await lock_task(db, ctx.task_id)
        await raise_task_progress(
            db, task, step_progress(steps, ctx.settings.task_progress_half_steps)
        )
        await bus.emit(
            db,
            user_id=ctx.user_id,
            type=kind,
            agent_id=ctx.agent_id,
            task_id=ctx.task_id,
            run_id=ctx.run_id,
            payload=payload,
        )
        await bus.commit(db)


async def _usage(ctx: RunContext, setup: RunSetup, raw: dict[str, Any]) -> None:
    """Tokens of one Codex turn: counted like any model call (the plan's own limits, no price)."""
    from sqlalchemy import select

    from app.services import usage as ledger

    usage = Usage(
        input_tokens=int(raw.get("input_tokens") or 0),
        output_tokens=int(raw.get("output_tokens") or 0)
        + int(raw.get("reasoning_output_tokens") or 0),
    )
    async with ctx.sessionmaker() as db:
        run = await lock_run(db, ctx.run_id)
        total = dict(run.usage or {})
        total["input_tokens"] = total.get("input_tokens", 0) + (usage.input_tokens or 0)
        total["output_tokens"] = total.get("output_tokens", 0) + (usage.output_tokens or 0)
        run.usage = total
        name = (await db.execute(select(Agent.name).where(Agent.id == ctx.agent_id))).scalar()
        await ledger.record(
            db,
            user_id=ctx.user_id,
            target=setup.target,
            usage=usage,
            source="agent",
            agent_id=ctx.agent_id,
            agent_name=name,
            task_id=ctx.task_id,
            run_id=ctx.run_id,
            agent_warn_percent=ctx.settings.agent_budget_warn_percent,
        )
        await bus.commit(db)


async def _take_notes(ctx: RunContext) -> str:
    from app.runtimes.native import owner_note

    async with ctx.sessionmaker() as db:
        run = await lock_run(db, ctx.run_id)
        inbox = list((run.state or {}).get("owner_inbox") or [])
        if not inbox:
            return ""
        run.state = {**(run.state or {}), "owner_inbox": []}
        await bus.emit(
            db,
            user_id=ctx.user_id,
            type="task.owner_message_read",
            agent_id=ctx.agent_id,
            task_id=ctx.task_id,
            run_id=ctx.run_id,
            payload={"count": len(inbox)},
        )
        await bus.commit(db)
    return owner_note([str(m["text"]) for m in inbox])
