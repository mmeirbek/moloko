"""The permission check (spec 15.2) and workspace path safety, without the engine."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import pytest

from app.models import Agent
from app.tools.base import (
    BaseTool,
    ScopeError,
    ToolCategory,
    ToolContext,
    ToolOutput,
    args_hash,
    object_schema,
)
from app.tools.policy import CatalogEntry, Verdict, authorize
from app.workspaces.paths import normalise, resolve
from tests.conftest import make_settings


class Fake(BaseTool):
    group = "test"
    title = "Fake"
    description = "fake"

    def __init__(self, name: str, category: ToolCategory) -> None:
        self.name, self.category = name, category
        self.input_schema = object_schema({"x": {"type": "string"}}, ["x"])

    async def check_scope(self, ctx: ToolContext, args: dict[str, Any]) -> None:
        if args["x"] == "outside":
            raise ScopeError("nope")

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        return ToolOutput("ok")


def agent(level: str, tools: list[str], overrides: dict[str, str] | None = None) -> Agent:
    return Agent(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        name="A",
        agent_type="autonomous",
        autonomy_level=level,
        allowed_tools=tools,
        permissions={"tools": overrides or {}},
    )


def ctx(a: Agent) -> ToolContext:
    async def no_ws() -> Any:
        raise AssertionError("not used")

    return ToolContext(
        user_id=a.user_id,
        agent=a,
        task_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        settings=make_settings(),
        sessionmaker=None,  # type: ignore[arg-type]
        workspace=no_ws,
        sandbox=None,
    )


async def decide(
    a: Agent,
    tool: BaseTool | None,
    args: dict[str, Any],
    *,
    enabled: bool = True,
    available: bool = True,
    name: str | None = None,
) -> tuple[Verdict, str]:
    entry = CatalogEntry(tool, enabled, available) if tool else None
    d = await authorize(
        agent=a, name=name or (tool.name if tool else "missing"), entry=entry, args=args, ctx=ctx(a)
    )
    return d.verdict, d.reason


@pytest.mark.parametrize(
    ("level", "category", "expected"),
    [
        ("supervised", ToolCategory.READ, Verdict.ALLOW),
        ("supervised", ToolCategory.WRITE, Verdict.REQUIRE_APPROVAL),
        ("supervised", ToolCategory.SENSITIVE, Verdict.REQUIRE_APPROVAL),
        ("balanced", ToolCategory.READ, Verdict.ALLOW),
        ("balanced", ToolCategory.WRITE, Verdict.ALLOW),
        ("balanced", ToolCategory.SENSITIVE, Verdict.REQUIRE_APPROVAL),
        ("restricted", ToolCategory.READ, Verdict.ALLOW),
        ("restricted", ToolCategory.WRITE, Verdict.REQUIRE_APPROVAL),
        ("restricted", ToolCategory.SENSITIVE, Verdict.DENY),
    ],
)
async def test_autonomy_matrix(level: str, category: ToolCategory, expected: Verdict) -> None:
    tool = Fake("t", category)
    assert (await decide(agent(level, ["t"]), tool, {"x": "a"}))[0] == expected


async def test_checks_in_order_and_denials() -> None:
    tool = Fake("t", ToolCategory.READ)
    a = agent("balanced", ["t"])
    assert (await decide(a, None, {"x": "a"}, name="ghost"))[0] == Verdict.DENY
    assert "turned off" in (await decide(a, tool, {"x": "a"}, enabled=False))[1]
    assert "not available" in (await decide(a, tool, {"x": "a"}, available=False))[1]
    assert "not allowed" in (await decide(agent("balanced", []), tool, {"x": "a"}))[1]
    verdict, reason = await decide(a, tool, {"y": 1})
    assert verdict == Verdict.DENY and reason.startswith("Invalid arguments")
    verdict, reason = await decide(a, tool, {"x": "outside"})
    assert verdict == Verdict.DENY and "scope" in reason


async def test_overrides_can_only_be_stricter() -> None:
    read, sensitive = Fake("r", ToolCategory.READ), Fake("s", ToolCategory.SENSITIVE)
    assert (await decide(agent("balanced", ["r"], {"r": "approve"}), read, {"x": "a"}))[
        0
    ] == Verdict.REQUIRE_APPROVAL
    assert (await decide(agent("balanced", ["r"], {"r": "deny"}), read, {"x": "a"}))[
        0
    ] == Verdict.DENY
    # There is no "allow" override: sensitive stays approval-only.
    loose = agent("balanced", ["s"], {"s": "allow"})
    assert (await decide(loose, sensitive, {"x": "a"}))[0] == Verdict.REQUIRE_APPROVAL


def test_args_hash_binds_exact_arguments() -> None:
    assert args_hash("fs_write", {"path": "a", "content": "1"}) == args_hash(
        "fs_write", {"content": "1", "path": "a"}
    )
    assert args_hash("fs_write", {"path": "a", "content": "1"}) != args_hash(
        "fs_write", {"path": "a", "content": "2"}
    )
    assert args_hash("fs_write", {"path": "a"}) != args_hash("fs_delete", {"path": "a"})


@pytest.mark.parametrize("bad", ["../x", "/etc/passwd", "a/../../b", "a\x00b", "x" * 600])
def test_paths_cannot_leave_the_workspace(bad: str) -> None:
    with pytest.raises(ScopeError):
        normalise(bad)


def test_symlinks_are_never_followed(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    (root / "dir").mkdir(parents=True)
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    os.symlink(outside, root / "link.txt")
    os.symlink(tmp_path, root / "dir" / "up")
    assert resolve(root, "dir/new.txt") == root / "dir" / "new.txt"
    for rel in ("link.txt", "dir/up/secret.txt", "dir/up"):
        with pytest.raises(ScopeError):
            resolve(root, rel)
