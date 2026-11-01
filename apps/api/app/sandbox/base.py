"""The ``Sandbox`` interface (docs/external-repositories.md rule 4).

The MVP implementation runs each command in a fresh, locked-down Docker container through
the sandbox runner service (``runner.py``). Another backend (for example E2B on Firecracker)
can implement the same interface later without touching the tools.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SandboxLimits:
    cpus: float
    memory_mb: int
    pids: int
    timeout_seconds: int


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int | None  # None: killed (timeout) or failed to start
    stdout: str
    stderr: str
    timed_out: bool = False
    oom_killed: bool = False
    truncated: bool = False
    duration_ms: int = 0


class SandboxUnavailable(Exception):
    """The sandbox service is not configured or cannot be reached."""


class Sandbox(Protocol):
    async def run(
        self, workspace_id: uuid.UUID, argv: list[str], *, timeout_seconds: int
    ) -> SandboxResult: ...

    async def health(self) -> dict[str, object]: ...
