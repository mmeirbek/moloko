"""The Orchestrator's plan (spec 14.3), parsed and validated in code.

Every part of a plan goes to one of the owner's persistent agents — an existing one, or a
new one the plan describes in ``new_agents`` when none fits (owner's decision, see
docs/decisions.md: no temporary subagents). A new agent gets the Orchestrator's model and
autonomy level and only tools the Orchestrator itself may use (a plan can never pick a
model name or grant itself more rights).
"""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


class PlanError(ValueError):
    pass


class NewAgentSpec(BaseModel):
    """A persistent agent the Orchestrator creates because none of the owner's fits."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=100)
    specialization: str = Field(default="generalist", max_length=64)
    description: str = Field(default="", max_length=500)
    instructions: str = Field(default="", max_length=4000)  # its role: the system prompt
    tools: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("a new agent needs a name")
        return value


class SubtaskSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str
    title: str = Field(min_length=1, max_length=200)
    instructions: str = Field(default="", max_length=8000)
    depends_on: list[str] = Field(default_factory=list)
    # Exact name of the agent that does this part: one of the owner's agents or one of the
    # plan's ``new_agents``.
    agent: str = Field(default="", max_length=100)

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
    new_agents: list[NewAgentSpec] = Field(default_factory=list)
    subtasks: list[SubtaskSpec] = Field(default_factory=list)
    review: bool = False  # the Orchestrator checks the combined result itself

    @model_validator(mode="after")
    def _consistent(self) -> Plan:
        if self.mode == "direct":
            if not (self.answer or "").strip():
                raise ValueError("a direct plan needs an answer")
            self.subtasks, self.new_agents = [], []
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
    agents: list[str] | None = None,
    max_new_agents: int = 0,
    tools: list[str] | None = None,
) -> tuple[Plan, list[str]]:
    """Parse + validate. Returns the plan and warnings about what was adjusted.

    ``agents``: the owner's agents (exact names); ``tools``: what a new agent may get (the
    Orchestrator's own tools)."""
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
    allowed_tools = set(tools or [])
    new: list[NewAgentSpec] = []
    for spec in plan.new_agents:
        key = spec.name.casefold()
        if key in roster:  # it exists already: use it instead of a twin
            warnings.append(f"'{spec.name}' already exists: that agent takes its parts")
            continue
        if any(n.name.casefold() == key for n in new):
            continue
        dropped = [t for t in spec.tools if t not in allowed_tools]
        if dropped:
            warnings.append(f"'{spec.name}': tools not available to it: {', '.join(dropped)}")
        spec.tools = [t for t in dict.fromkeys(spec.tools) if t in allowed_tools]
        new.append(spec)
    if len(new) > max_new_agents:
        raise PlanError(
            f"the plan creates {len(new)} new agents; at most {max_new_agents} — give parts "
            "to the owner's agents or let one new agent do several parts"
        )
    plan.new_agents = new
    names = {**roster, **{n.name.casefold(): n.name for n in new}}
    for sub in plan.subtasks:
        canonical = names.get(" ".join(sub.agent.split()).casefold()) if sub.agent else None
        if canonical is None:
            available = ", ".join(sorted(names.values())) or "none"
            raise PlanError(
                f"subtask '{sub.key}' must name the agent that does it (available: {available}"
                + ("; or describe a new one in new_agents" if max_new_agents else "")
                + ")"
            )
        sub.agent = canonical
    return plan, warnings
