"""The permission check (spec 15.2). Runs in the backend before EVERY tool execution.

    authorize(agent, tool, args, context) -> ALLOW | REQUIRE_APPROVAL | DENY (+ reason)

1. The tool exists, is enabled and available, and is in ``agent.allowed_tools``.
2. The arguments match the tool's schema and stay inside the allowed scope.
3. Category (possibly narrowed by the arguments) + autonomy level (spec 14.2):

   ============  ======  =================  =================
   level         read    write              sensitive
   ============  ======  =================  =================
   supervised    allow   approval           approval
   balanced      allow   allow              approval
   restricted    allow   approval           deny
   ============  ======  =================  =================

   Per-tool overrides in ``agent.permissions["tools"]`` can only be stricter
   (``"approve"`` or ``"deny"``).
4. ``sensitive`` always needs approval (or is denied).
5. The decision and its reason are written to ``audit_logs``.

Model output never changes this result: the model only proposes calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import jsonschema
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AutonomyLevel
from app.models.agent import Agent
from app.services.audit import AuditService
from app.tools.base import BaseTool, ScopeError, ToolCategory, ToolContext


class Verdict(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    reason: str
    category: ToolCategory | None = None


@dataclass(frozen=True)
class CatalogEntry:
    tool: BaseTool
    enabled: bool
    available: bool


def tool_override(agent: Agent, name: str) -> str | None:
    tools = (agent.permissions or {}).get("tools") or {}
    value = tools.get(name) if isinstance(tools, dict) else None
    return value if value in ("approve", "deny") else None


def _by_autonomy(level: str, category: ToolCategory) -> Decision:
    if category == ToolCategory.SENSITIVE:
        if level == AutonomyLevel.RESTRICTED.value:
            return Decision(
                Verdict.DENY, "Sensitive actions are not allowed at the restricted level.", category
            )
        return Decision(
            Verdict.REQUIRE_APPROVAL, "Sensitive actions always need approval.", category
        )
    if category == ToolCategory.WRITE:
        if level == AutonomyLevel.BALANCED.value:
            return Decision(Verdict.ALLOW, "Write action allowed at the balanced level.", category)
        return Decision(
            Verdict.REQUIRE_APPROVAL, f"Write actions need approval at the {level} level.", category
        )
    return Decision(Verdict.ALLOW, "Read action.", category)


def schema_error(schema: dict[str, Any], args: dict[str, Any]) -> str | None:
    try:
        jsonschema.validate(args, schema)
    except jsonschema.ValidationError as exc:
        where = "/".join(str(p) for p in exc.absolute_path)
        return f"{where + ': ' if where else ''}{exc.message}"[:300]
    except jsonschema.SchemaError:
        return "the tool's schema is invalid"
    return None


async def authorize(
    *,
    agent: Agent,
    name: str,
    entry: CatalogEntry | None,
    args: dict[str, Any],
    ctx: ToolContext,
) -> Decision:
    # 1. enabled + allowed
    if entry is None:
        return Decision(Verdict.DENY, f"There is no tool named '{name}'.")
    if not entry.enabled:
        return Decision(Verdict.DENY, "This tool is turned off.")
    if not entry.available:
        return Decision(Verdict.DENY, "This tool is not available right now (not configured).")
    if name not in (agent.allowed_tools or []):
        return Decision(Verdict.DENY, "This agent is not allowed to use this tool.")
    # 2. arguments + scope
    if not isinstance(args, dict):
        return Decision(Verdict.DENY, "Invalid arguments: expected an object.")
    error = schema_error(entry.tool.input_schema, args)
    if error:
        return Decision(Verdict.DENY, f"Invalid arguments: {error}")
    try:
        await entry.tool.check_scope(ctx, args)
    except ScopeError as exc:
        return Decision(Verdict.DENY, f"Outside the allowed scope: {exc}")
    # 3. + 4. category and autonomy
    category = await entry.tool.category_for(ctx, args)
    override = tool_override(agent, name)
    if override == "deny":
        return Decision(Verdict.DENY, "The owner blocked this tool for this agent.", category)
    decision = _by_autonomy(agent.autonomy_level, category)
    if override == "approve" and decision.verdict == Verdict.ALLOW:
        decision = Decision(
            Verdict.REQUIRE_APPROVAL, "The owner wants to approve every use of this tool.", category
        )
    return decision


async def audit_decision(
    db: AsyncSession,
    *,
    agent: Agent,
    name: str,
    decision: Decision,
    args_digest: str,
    task_id: Any,
    run_id: Any,
) -> None:
    """Spec 15.2 step 5. Arguments are not stored here — only their hash."""
    await AuditService(db).record(
        "tool.authorized",
        "denied" if decision.verdict == Verdict.DENY else "success",
        actor_type="agent",
        actor_id=agent.id,
        user_id=agent.user_id,
        resource_type="tool",
        resource_id=name,
        details={
            "verdict": decision.verdict.value,
            "reason": decision.reason,
            "category": decision.category.value if decision.category else None,
            "autonomy": agent.autonomy_level,
            "args_hash": args_digest,
            "task_id": str(task_id),
            "run_id": str(run_id),
        },
    )
