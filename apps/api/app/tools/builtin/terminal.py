"""Terminal tool: one command in a fresh sandbox container (spec 15.6, 16).

The command is split like a shell would (``shlex``) but runs WITHOUT a shell: no pipes,
redirects or ``&&``. The program must be on ``SANDBOX_ALLOWED_COMMANDS``. This is intent
control; the isolation itself is the container (no network, non-root, limits).

``network: "packages"`` (opt-in per call) lets the command download packages: the container
then joins an internal network whose only exit is the ``egress-packages`` proxy, which lets
HTTPS through to ``SANDBOX_PACKAGE_HOSTS`` (the npm and PyPI registries) and nothing else.
Such a call is **sensitive** — the owner approves it (or allows it for that program with
«больше не спрашивать»), and the restricted level never runs it. Without it: no network.
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

PACKAGES = "packages"
# What npm / pip / node print when they find no network (to tell the model what to do).
OFFLINE_SIGNS = (
    "EAI_AGAIN",
    "ENOTFOUND",
    "ENETUNREACH",
    "Temporary failure in name resolution",
    "Network is unreachable",
    "Failed to establish a new connection",
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


def wants_packages(args: dict[str, Any]) -> bool:
    return args.get("network") == PACKAGES


class TerminalRun(BaseTool):
    name = "terminal_run"
    title = "Run a command"
    description = (
        "Run one command in an isolated sandbox; the current folder is your workspace. "
        "Installed: python3 and pip, Node.js 22 with npm and npx, git, make and basic file "
        "tools (only allowed programs). No shell: no pipes, redirects, `&&` or `cd`, so run "
        "commands one at a time and point the program at a sub-folder itself: "
        "`npm --prefix app ci`, `npm --prefix app run lint`, `npm --prefix app exec -- tsc "
        "--noEmit`, `git -C app status`, `make -C app`. No network unless you set "
        'network "packages": then the command may download packages from the npm and '
        "PyPI registries only (for `npm ci`, `npm install`, `pip install --user …`); that "
        "needs the owner's approval, so install once and run the other commands without it. "
        "Give a larger timeout_seconds for installs and builds (the default is short)."
    )
    group = "terminal"
    category = ToolCategory.WRITE
    input_schema = object_schema(
        {
            "command": string_prop("For example: python main.py --check"),
            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 3600},
            "network": {
                "type": "string",
                "enum": ["none", PACKAGES],
                "description": "none (default) or packages: downloads from the npm and PyPI "
                "registries only, with the owner's approval",
            },
        },
        ["command"],
    )

    async def available(self, db: AsyncSession, user_id: Any, settings: Settings) -> bool:
        return bool(settings.sandbox_url and settings.sandbox_runner_token)

    def timeout_for(self, settings: Settings) -> float:
        return settings.sandbox_timeout_seconds + 30  # the sandbox enforces its own limit

    async def check_scope(self, ctx: ToolContext, args: dict[str, Any]) -> None:
        parse_command(args["command"], ctx.settings.sandbox_allowed_commands)

    async def category_for(self, ctx: ToolContext, args: dict[str, Any]) -> ToolCategory:
        # Reaching the internet (even only the registries) is stricter than a local command.
        return ToolCategory.SENSITIVE if wants_packages(args) else ToolCategory.WRITE

    def describe(self, args: dict[str, Any]) -> OperationInfo:
        if wants_packages(args):
            return self._describe_packages(args, ["the npm and PyPI registries"])
        return OperationInfo(
            summary=f"Run: {args['command'][:300]}",
            resources=["workspace (sandbox, no network)"],
            consequences="The command may create, change or delete files in the task workspace.",
        )

    def describe_for(self, settings: Settings, args: dict[str, Any]) -> OperationInfo:
        if wants_packages(args):
            return self._describe_packages(args, settings.sandbox_package_hosts)
        return self.describe(args)

    def _describe_packages(self, args: dict[str, Any], hosts: list[str]) -> OperationInfo:
        return OperationInfo(
            summary=f"Run with package downloads: {args['command'][:300]}",
            resources=["workspace (sandbox)", *(f"internet: {h} (HTTPS)" for h in hosts[:10])],
            consequences=(
                "The command may download packages from these sites only and run their "
                "install scripts inside the sandbox; it may create, change or delete files "
                "in the task workspace."
            ),
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        if ctx.sandbox is None:
            raise ToolFailed("The sandbox is not configured.")
        argv = parse_command(args["command"], ctx.settings.sandbox_allowed_commands)
        network = PACKAGES if wants_packages(args) else "none"
        timeout = min(
            int(args.get("timeout_seconds") or ctx.settings.sandbox_default_timeout_seconds),
            ctx.settings.sandbox_timeout_seconds,
        )
        ws = await ctx.workspace()
        root = workspace_dir(ctx.settings, ws.id)
        scan = (ctx.settings.workspace_max_files, ctx.settings.workspace_untracked_dirs)
        before = await asyncio.to_thread(snapshot, root, *scan)
        try:
            result = await ctx.sandbox.run(ws.id, argv, timeout_seconds=timeout, network=network)
        except SandboxUnavailable as exc:
            raise ToolFailed(str(exc)) from None
        after = await asyncio.to_thread(snapshot, root, *scan)
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
            if timeout < ctx.settings.sandbox_timeout_seconds:
                status += f"; give timeout_seconds up to {ctx.settings.sandbox_timeout_seconds}"
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
        if failed and network == "none" and any(s in result.stderr for s in OFFLINE_SIGNS):
            parts.append('(no network: to download packages, run it again with network "packages")')
        return ToolOutput("\n".join(parts), is_error=failed)


TERMINAL_TOOLS: tuple[BaseTool, ...] = (TerminalRun(),)
