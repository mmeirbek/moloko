"""Scripted replies for the offline mock provider (tests, CI, demos) — never used with
real providers. Steered by directives in the task text:

  [[mock:plan:N]]    delegate N subtasks (otherwise: direct answer)
  [[mock:chain]]     each subtask depends on the previous one
  [[mock:review]]    ask for a reviewer step
  [[mock:nested]]    the first subtask delegates again ([[mock:plan:2]] inside it)
  [[mock:deep]]      every subtask asks to delegate again (exercises the depth limit)
  [[mock:badplan]]   the first planning answer is not JSON (exercises plan retry)
  [[mock:alwaysbad]] every planning answer is invalid
  [[mock:failpart:K]] subtask K fails with a provider error
"""

from __future__ import annotations

import json
import re

from app.orchestrator.prompts import PROTOCOL_PLAN, PROTOCOL_REVIEW, PROTOCOL_SYNTHESIS
from app.providers.base import ChatRequest, ChatResult, Usage
from app.providers.mock_provider import last_user_text, register_scripted_handler

_PLAN = re.compile(r"\[\[mock:plan:(\d+)\]\]")
_FAIL = re.compile(r"\[\[mock:failpart:(\d+)\]\]")


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
        delegate = False
        if "[[mock:deep]]" in task_text:
            instructions += " [[mock:plan:2]] [[mock:deep]]"
            delegate = True
        elif "[[mock:nested]]" in task_text and i == 1:
            instructions += " [[mock:plan:2]]"
            delegate = True
        if fail and int(fail.group(1)) == i:
            instructions += " [[mock:error:bad_request]]"
        if "[[mock:slowparts]]" in task_text:
            instructions += " [[mock:slow]]"
        subtasks.append(
            {
                "key": f"part-{i}",
                "title": f"Part {i}",
                "specialization": "research" if i % 2 else "analysis",
                "instructions": instructions,
                "depends_on": [f"part-{i - 1}"] if "[[mock:chain]]" in task_text and i > 1 else [],
                "delegate": delegate,
            }
        )
    return json.dumps(
        {
            "mode": "delegate",
            "summary": f"Split into {n} parts",
            "review": "[[mock:review]]" in task_text,
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
        return ChatResult(
            text=f"Final answer combining: {parts}", usage=Usage(10, 10), stop_reason="end_turn"
        )
    if PROTOCOL_REVIEW in system:
        return ChatResult(text="No issues", usage=Usage(5, 2), stop_reason="end_turn")
    return None


register_scripted_handler(scripted)
