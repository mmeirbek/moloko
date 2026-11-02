"""The Orchestrator's plan (spec 14.3), parsed and validated in code.

Each subtask concretises a subagent as ⟨instructions, context, tools, model⟩ (idea from
AOrchestra, re-implemented): instructions = ``instructions``; context = the root task +
results of ``depends_on``; tools = ``tools`` ∩ what the orchestrator may use; model =
the orchestrator's model (a plan can never pick an arbitrary model name).
"""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


class PlanError(ValueError):
    pass


class SubtaskSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str
    title: str = Field(min_length=1, max_length=200)
    specialization: str = Field(default="generalist", max_length=64)
    instructions: str = Field(default="", max_length=8000)
    depends_on: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    delegate: bool = False  # may this subagent plan and delegate further (depth permitting)?
    # Give this part to one of the owner's persistent agents (exact name) instead of a new
    # subagent. That agent works with its own model, tools, autonomy and memory.
    agent: str | None = Field(default=None, max_length=100)

    @field_validator("key")
    @classmethod
    def _key(cls, value: str) -> str:
        value = value.strip().lower()
        if not KEY_RE.match(value):
            raise ValueError("subtask keys are short slugs: a-z, 0-9, '-' or '_'")
        return value


class Plan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mode: Literal["direct", "delegate"]
    answer: str | None = None
    summary: str = Field(default="", max_length=2000)
    subtasks: list[SubtaskSpec] = Field(default_factory=list)
    review: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> Plan:
        if self.mode == "direct":
            if not (self.answer or "").strip():
                raise ValueError("a direct plan needs an answer")
            self.subtasks = []
            return self
        if not self.subtasks:
            raise ValueError("a delegate plan needs at least one subtask")
        keys = [s.key for s in self.subtasks]
        if len(set(keys)) != len(keys):
            raise ValueError("subtask keys must be unique")
        for sub in self.subtasks:
            unknown = set(sub.depends_on) - set(keys)
            if unknown:
                raise ValueError(
                    f"subtask '{sub.key}' depends on unknown subtasks: {sorted(unknown)}"
                )
            if sub.key in sub.depends_on:
                raise ValueError(f"subtask '{sub.key}' depends on itself")
        _check_acyclic(self.subtasks)
        return self


def _check_acyclic(subtasks: list[SubtaskSpec]) -> None:
    deps = {s.key: set(s.depends_on) for s in subtasks}
    done: set[str] = set()
    while deps:
        ready = [k for k, d in deps.items() if d <= done]
        if not ready:
            raise ValueError(f"subtask dependencies form a cycle: {sorted(deps)}")
        for k in ready:
            done.add(k)
            del deps[k]


def extract_json(text: str) -> object:
    """Models sometimes wrap JSON in prose or ``` fences: take the outermost object."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise PlanError("no JSON object in the planner's answer")
        candidate = text[start : end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise PlanError(f"the planner's JSON is malformed: {exc.msg}") from None


def parse_plan(
    text: str,
    *,
    max_subtasks: int,
    can_delegate_further: bool,
    agents: list[str] | None = None,
) -> tuple[Plan, list[str]]:
    """Parse + validate. Returns the plan and warnings about what was adjusted."""
    try:
        plan = Plan.model_validate(extract_json(text))
    except ValidationError as exc:
        first = exc.errors()[0]
        raise PlanError(
            f"invalid plan: {first.get('msg')} at {'.'.join(map(str, first.get('loc', ())))}"
        ) from None
    warnings: list[str] = []
    if len(plan.subtasks) > max_subtasks:
        raise PlanError(f"the plan has {len(plan.subtasks)} subtasks; the limit is {max_subtasks}")
    roster = {name.casefold(): name for name in agents or []}
    for sub in plan.subtasks:
        if sub.agent is None or not sub.agent.strip():
            sub.agent = None
            continue
        canonical = roster.get(sub.agent.strip().casefold())
        if canonical is None:
            available = ", ".join(sorted(roster.values())) or "none"
            raise PlanError(
                f"subtask '{sub.key}' names an unknown agent '{sub.agent}' (available: {available})"
            )
        sub.agent, sub.delegate, sub.tools = canonical, False, []
    if not can_delegate_further:
        for sub in plan.subtasks:
            if sub.delegate:
                sub.delegate = False
                warnings.append(
                    f"'{sub.key}': further delegation refused (maximum subagent depth reached)"
                )
    return plan, warnings
