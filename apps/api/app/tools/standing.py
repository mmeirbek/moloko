"""Standing approvals («Одобрить и больше не спрашивать», the owner's decision — see
docs/decisions.md): when the owner approves an action and asks not to be asked again, the
agent may do that kind of action from then on without an approval.

What "that kind" is depends on the tool:

* ``terminal_run`` — the programs the command runs (``python3``, ``npm``, ``git``…). A later
  command is covered only if EVERY program in it is allowed; command substitution
  (``$(…)``, backticks) and anything that cannot be parsed always ask again. With package
  downloads (``network: "packages"``) the scope is ``packages:<program>``: it also covers
  that program without network, but an offline approval never covers downloads;
* GitHub tools — the repository; ``browser_screenshot`` — the site; ``agent_ask`` /
  ``agent_tell`` — the colleague;
* everything else — the tool itself (e.g. writing files in the agent's own workspace).

Stored on the agent (``agents.permissions["always"]``), never copied to templates or other
agents; the owner removes them on the agent's page. They only turn "needs approval" into
"allowed": "denied" stays denied, and the owner's "approve every use" override still asks.
"""

from __future__ import annotations

import re
import shlex
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from app.models.agent import Agent

MAX_RULES = 200
# terminal_run with network "packages": its scopes are "packages:<program>" (":" never
# occurs in a program name), so allowing `npm` offline does not allow downloads.
PACKAGES = "packages:"
_PROGRAM = re.compile(r"^[A-Za-z0-9_.+-]{1,64}$")
_OPERATOR = re.compile(r"^[;&|\n]+$")


def programs(command: str) -> list[str] | None:
    """The programs a shell command runs, in order; None when that cannot be said safely."""
    if "$(" in command or "`" in command:
        return None
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:  # unbalanced quotes
        return None
    found: list[str] = []
    expect_program = True
    for token in tokens:
        if _OPERATOR.match(token):
            expect_program = True
            continue
        if expect_program:
            name = token.rsplit("/", 1)[-1]
            if not _PROGRAM.match(name):
                return None  # FOO=1 cmd, (subshell), <(…) and the like: ask
            found.append(name)
            expect_program = False
    return found or None


def scopes(tool: str, args: dict[str, Any]) -> list[str] | None:
    """What a standing approval of this call would cover ("" = the whole tool);
    None when it cannot be offered."""
    if tool == "terminal_run":
        found = programs(str(args.get("command", "")))
        if not found:
            return None
        prefix = PACKAGES if args.get("network") == "packages" else ""
        return list(dict.fromkeys(prefix + p for p in found))
    if tool.startswith("github_"):
        repo = str(args.get("repo", "")).strip().casefold()
        return [repo] if repo else None
    if tool == "browser_screenshot":
        host = (urlsplit(str(args.get("url", ""))).hostname or "").casefold()
        return [host] if host else None
    if tool in ("agent_ask", "agent_tell"):
        agent = str(args.get("agent", "")).strip().casefold()
        return [agent] if agent else None
    return [""]


def rules(agent: Agent) -> list[dict[str, Any]]:
    value = (agent.permissions or {}).get("always") or []
    return [r for r in value if isinstance(r, dict) and isinstance(r.get("tool"), str)]


def covering(agent: Agent, tool: str, args: dict[str, Any]) -> dict[str, Any] | None:
    """The standing approval that allows this call, if any."""
    own = [r for r in rules(agent) if r["tool"] == tool]
    if not own:
        return None
    if any(r.get("scope", "") == "" for r in own):
        return next(r for r in own if r.get("scope", "") == "")
    needed = scopes(tool, args)
    if not needed or needed == [""]:
        return None
    allowed = {str(r.get("scope", "")): r for r in own}

    def rule_for(scope: str) -> dict[str, Any] | None:
        # "npm with package downloads" also covers npm without network, never the reverse
        found = allowed.get(scope)
        if found is None and tool == "terminal_run" and not scope.startswith(PACKAGES):
            found = allowed.get(PACKAGES + scope)
        return found

    found = [rule_for(s) for s in needed]
    return found[0] if all(found) else None


def add(
    agent: Agent, tool: str, args: dict[str, Any], approval_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Remember the owner's "don't ask again" for this agent. Returns the new rules."""
    wanted = scopes(tool, args)
    if wanted is None:
        return []
    existing = rules(agent)
    have = {(r["tool"], str(r.get("scope", ""))) for r in existing}
    now = datetime.now(UTC).isoformat()
    new = [
        {
            "id": str(uuid.uuid4()),
            "tool": tool,
            "scope": s,
            "since": now,
            "approval_id": str(approval_id),
        }
        for s in wanted
        if (tool, s) not in have
    ]
    if new:
        agent.permissions = {**(agent.permissions or {}), "always": (existing + new)[-MAX_RULES:]}
    return new


def remove(agent: Agent, rule_id: str) -> dict[str, Any] | None:
    existing = rules(agent)
    gone = next((r for r in existing if r.get("id") == rule_id), None)
    if gone is not None:
        agent.permissions = {
            **(agent.permissions or {}),
            "always": [r for r in existing if r.get("id") != rule_id],
        }
    return gone
