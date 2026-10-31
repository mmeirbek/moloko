"""Runtime adapter contract (spec 13.3).

A runtime executes one agent run. It reports everything through the shared event
system (``RunContext``) and never decides permissions itself. The UI does not depend
on which runtime ran an agent (invariant 8).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.providers.gateway import ModelGateway

if TYPE_CHECKING:
    from app.agents.control import RunControl


@dataclass
class RunContext:
    run_id: uuid.UUID
    task_id: uuid.UUID
    agent_id: uuid.UUID
    user_id: uuid.UUID
    fresh: bool  # False when resuming from a checkpoint
    sessionmaker: async_sessionmaker[AsyncSession]
    gateway: ModelGateway
    settings: Settings
    control: RunControl


class AgentRuntime(Protocol):
    name: str

    async def start(self, ctx: RunContext) -> None:
        """Run (or resume) the task. Must leave the task in a correct state when it returns."""

    async def cancel(self, run_id: uuid.UUID) -> None:
        """Best-effort interruption of an in-flight run."""
