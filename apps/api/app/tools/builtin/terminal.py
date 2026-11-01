"""Terminal tool: one command in a fresh sandbox container (spec 15.6, 16).

The command is split like a shell would (``shlex``) but runs WITHOUT a shell: no pipes,
redirects or ``&&``. The program must be on ``SANDBOX_ALLOWED_COMMANDS``. This is intent
control; the isolation itself is the container (no network, non-root, limits).
"""

from __future__ import annotations

import asyncio
import shlex
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.sandbox.base import SandboxUnavailable
from app.services.workspaces import changed_paths, record_changes, snapshot, workspace_dir
from app.tools.base import (
    BaseTool,
    OperationInfo,
    ScopeError,
    ToolCategory,
    ToolContext,
    ToolFailed,
    ToolOutput,
    object_schema,
    string_prop,
)


def parse_command(command: str, allowed: list[str]) -> list[str]:
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise ScopeError(f"cannot parse the command: {exc}") from None
    if not argv:
        raise ScopeError("empty command")
    program = PurePosixPath(argv[0]).name
    if program != argv[0]:
        raise ScopeError("give the program name only, not a path")
    if program not in allowed:
        raise ScopeError(f"'{program}' is not an allowed command")
    return argv


class TerminalRun(BaseTool):
    name = "terminal_run"
    title = "Run a command"
    description = (
        "Run one command in an isolated sandbox with the task workspace as the current folder. "
        "No shell features (pipes, redirects, &&); no network. Allowed programs are limited."
    )
    group = "terminal"
    category = ToolCategory.WRITE
    input_schema = object_schema(
        {
            "command": string_prop("For example: python main.py --check"),
            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 3600},
        },
        ["command"],
    )

    async def available(self, db: AsyncSession, user_id: Any, settings: Settings) -> bool:
        return bool(settings.sandbox_url and settings.sandbox_runner_token)

    async def check_scope(self, ctx: ToolContext, args: dict[str, Any]) -> None:
        parse_command(args["command"], ctx.settings.sandbox_allowed_commands)

    def describe(self, args: dict[str, Any]) -> OperationInfo:
        return OperationInfo(
            summary=f"Run: {args['command'][:300]}",
            resources=["workspace (sandbox, no network)"],
            consequences="The command may create, change or delete files in the task workspace.",
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        if ctx.sandbox is None:
            raise ToolFailed("The sandbox is not configured.")
        argv = parse_command(args["command"], ctx.settings.sandbox_allowed_commands)
        timeout = min(
            int(args.get("timeout_seconds") or ctx.settings.sandbox_timeout_seconds),
            ctx.settings.sandbox_timeout_seconds,
        )
        ws = await ctx.workspace()
        root = workspace_dir(ctx.settings, ws.id)
        before = await asyncio.to_thread(snapshot, root, ctx.settings.workspace_max_files)
        try:
            result = await ctx.sandbox.run(ws.id, argv, timeout_seconds=timeout)
        except SandboxUnavailable as exc:
            raise ToolFailed(str(exc)) from None
        after = await asyncio.to_thread(snapshot, root, ctx.settings.workspace_max_files)
        changed, deleted = changed_paths(before, after)
        if changed or deleted:
            async with ctx.sessionmaker() as db:
                await record_changes(
                    db,
                    ctx.settings,
                    workspace=ws,
                    changed=changed,
                    deleted=deleted,
                    task_id=ctx.task_id,
                    agent_id=ctx.agent.id,
                    tool_call_id=ctx.tool_call_id,
                )
                await db.commit()
        if result.timed_out:
            status = f"killed after {timeout} s (time limit)"
        elif result.oom_killed:
            status = "killed: out of memory"
        else:
            status = f"exit code {result.exit_code}"
        parts = [status]
        if result.stdout:
            parts.append("--- stdout ---\n" + result.stdout)
        if result.stderr:
            parts.append("--- stderr ---\n" + result.stderr)
        if result.truncated:
            parts.append("(output truncated)")
        if changed or deleted:
            parts.append(f"files changed: {len(changed)}, deleted: {len(deleted)}")
        failed = result.timed_out or result.oom_killed or result.exit_code != 0
        return ToolOutput("\n".join(parts), is_error=failed)


TERMINAL_TOOLS: tuple[BaseTool, ...] = (TerminalRun(),)
