"""What every tool is (spec 15.1) and what it gets when it runs.

A tool declares its name, description, input JSON schema, category and limits. It can
narrow its category from the arguments (e.g. a GitHub commit to the default branch is
``sensitive``), check that the arguments stay inside the allowed scope, and describe the
operation for an approval request. ``run`` only executes — it is never called before
``authorize`` (``app/tools/policy.py``) has allowed the exact call.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.tooling import Workspace
    from app.sandbox.base import Sandbox


class ToolCategory(StrEnum):
    READ = "read"
    WRITE = "write"
    SENSITIVE = "sensitive"


RANK = {ToolCategory.READ: 0, ToolCategory.WRITE: 1, ToolCategory.SENSITIVE: 2}


def stricter(a: ToolCategory, b: ToolCategory) -> ToolCategory:
    return a if RANK[a] >= RANK[b] else b


class ScopeError(Exception):
    """The arguments point outside what this agent may touch."""


class ToolFailed(Exception):
    """An expected failure with a message that is safe to show to the model and the owner."""


@dataclass(frozen=True)
class OperationInfo:
    """What the owner sees in an approval request (spec 15.4)."""

    summary: str
    resources: list[str] = field(default_factory=list)
    consequences: str = ""


@dataclass
class ToolOutput:
    text: str
    is_error: bool = False


@dataclass
class ToolContext:
    """Everything a tool may use. Built per run by the tool runner."""

    user_id: uuid.UUID
    agent: Agent
    task_id: uuid.UUID
    run_id: uuid.UUID
    settings: Settings
    sessionmaker: async_sessionmaker[AsyncSession]
    workspace: Callable[[], Awaitable[Workspace]]  # resolved (and created) on first use
    sandbox: Sandbox | None
    tool_call_id: uuid.UUID | None = None  # the tool_calls row of the current call


class BaseTool(ABC):
    name: str
    title: str
    description: str
    group: str  # files | terminal | web | github | memory | mcp
    category: ToolCategory
    input_schema: dict[str, Any]
    timeout_seconds: float | None = None  # None = TOOL_TIMEOUT_SECONDS

    async def available(self, db: AsyncSession, user_id: uuid.UUID, settings: Settings) -> bool:
        """False when the tool cannot work right now (integration not configured, …)."""
        return True

    async def category_for(self, ctx: ToolContext, args: dict[str, Any]) -> ToolCategory:
        return self.category

    async def check_scope(self, ctx: ToolContext, args: dict[str, Any]) -> None:  # noqa: B027
        """Raise ``ScopeError`` when the arguments leave the allowed scope."""

    def describe(self, args: dict[str, Any]) -> OperationInfo:
        return OperationInfo(summary=f"{self.title}: {json.dumps(args, ensure_ascii=False)[:300]}")

    @abstractmethod
    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput: ...


def args_hash(tool_name: str, args: dict[str, Any]) -> str:
    """Stable hash of one exact operation; an approval is bound to it (spec 15.4)."""
    canonical = json.dumps(
        {"tool": tool_name, "args": args}, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def string_prop(description: str, **extra: Any) -> dict[str, Any]:
    return {"type": "string", "description": description, **extra}


def object_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
