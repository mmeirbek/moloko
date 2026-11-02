"""Scripted replies for the offline mock provider (tests, CI, demos) — never used with
real providers. Steered by directives in the task text:

  [[mock:plan:N]]     delegate N parts (otherwise: direct answer); parts go to new agents
                      "Researcher" (odd parts) and "Analyst" (even parts) — or to the
                      owner's agents of those names when they exist
  [[mock:spread]]     every part gets its own new agent "Helper N" (parallel parts)
  [[mock:assign:X]]   the last part goes to the owner's agent X
  [[mock:chain]]      each part depends on the previous one
  [[mock:review]]     the Orchestrator checks the combined result
  [[mock:badplan]]    the first planning answer is not JSON (exercises plan retry)
  [[mock:alwaysbad]]  every planning answer is invalid
  [[mock:failpart:K]] part K fails with a provider error
  [[mock:slowparts]]  every part answers slowly
"""

from __future__ import annotations

import json
import re

from app.orchestrator.prompts import PROTOCOL_PLAN, PROTOCOL_SYNTHESIS
from app.providers.base import ChatRequest, ChatResult, Usage
from app.providers.mock_provider import last_user_text, register_scripted_handler

_PLAN = re.compile(r"\[\[mock:plan:(\d+)\]\]")
_FAIL = re.compile(r"\[\[mock:failpart:(\d+)\]\]")
_ASSIGN = re.compile(r"\[\[mock:assign:([^\]]+)\]\]")  # the last part goes to this agent
NEW_AGENTS = (
    {"name": "Researcher", "specialization": "research", "description": "Finds facts."},
    {"name": "Analyst", "specialization": "analysis", "description": "Draws conclusions."},
)


def _plan(task_text: str, already_retried: bool) -> str:
    if "[[mock:alwaysbad]]" in task_text or (
        "[[mock:badplan]]" in task_text and not already_retried
    ):
        return "I think we should split this up!"  # not JSON
    match = _PLAN.search(task_text)
    if not match:
        first_line = task_text.splitlines()[0] if task_text else ""
        return json.dumps({"mode": "direct", "answer": f"Direct answer: {first_line}"})
    n = int(match.group(1))
    fail = _FAIL.search(task_text)
    subtasks = []
    for i in range(1, n + 1):
        instructions = f"Handle part {i}."
        if fail and int(fail.group(1)) == i:
            instructions += " [[mock:error:bad_request]]"
        if "[[mock:slowparts]]" in task_text:
            instructions += " [[mock:slow]]"
        chained = "[[mock:chain]]" in task_text and i > 1
        spread = "[[mock:spread]]" in task_text
        subtasks.append(
            {
                "key": f"part-{i}",
                "title": f"Part {i}",
                "agent": f"Helper {i}" if spread else NEW_AGENTS[(i - 1) % 2]["name"],
                "instructions": instructions,
                "depends_on": [f"part-{i - 1}"] if chained else [],
            }
        )
    assign = _ASSIGN.search(task_text)
    if assign and subtasks:
        subtasks[-1]["agent"] = assign.group(1).strip()
    used = {s["agent"] for s in subtasks}
    if "[[mock:spread]]" in task_text:
        new_agents = [
            {"name": f"Helper {i}", "specialization": "generalist", "description": "", "tools": []}
            for i in range(1, n + 1)
            if f"Helper {i}" in used
        ]
    else:
        new_agents = [dict(a, instructions="", tools=[]) for a in NEW_AGENTS if a["name"] in used]
    return json.dumps(
        {
            "mode": "delegate",
            "summary": f"Split into {n} parts",
            "review": "[[mock:review]]" in task_text,
            "new_agents": new_agents,
            "subtasks": subtasks,
        }
    )


def scripted(req: ChatRequest) -> ChatResult | None:
    system = req.system or ""
    if PROTOCOL_PLAN in system:
        first = next((m.content for m in req.messages if m.role == "user"), "")
        retried = sum(1 for m in req.messages if m.role == "user") > 1
        return ChatResult(text=_plan(first, retried), usage=Usage(10, 10), stop_reason="end_turn")
    if PROTOCOL_SYNTHESIS in system:
        inputs = re.findall(r'<input from="([^"]+)" type="([^"]+)">', last_user_text(req))
        parts = ", ".join(f"{who} ({kind})" for who, kind in inputs)
        checked = " (checked)" if "check the combined result critically" in system else ""
        return ChatResult(
            text=f"Final answer combining: {parts}{checked}",
            usage=Usage(10, 10),
            stop_reason="end_turn",
        )
    return None


register_scripted_handler(scripted)
