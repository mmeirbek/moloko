"""Deterministic offline provider for tests, CI and demos (no network, no cost).

Enabled only with ENABLE_MOCK_PROVIDER=true. Behaviour is driven by the last user
message, so tests can steer it:

* ``[[mock:error:<kind>]]``  raise ProviderError(<kind>) (e.g. rate_limited, auth_failed)
* ``[[mock:slow]]``          stream slowly / answer after 3 s (cancellation, live-status tests)
* ``[[mock:sleep:N]]``       answer after N seconds (max 60)
* anything else              "Echo: <message>"

Agent-related behaviours (planning, tool calls) are added by ``scripted_reply``
handlers registered from the agent modules, so the mock never hardcodes their prompts.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Callable
from typing import cast

from app.providers.base import (
    ERROR_MESSAGES,
    ChatChunk,
    ChatRequest,
    ChatResult,
    ErrorKind,
    ModelInfo,
    ProviderError,
    ToolCall,
    Usage,
)

MOCK_MODELS = (ModelInfo("mock-fast", "Mock Fast"), ModelInfo("mock-smart", "Mock Smart"))
_ERROR_RE = re.compile(r"\[\[mock:error:([a-z_]+)\]\]")
_SLEEP_RE = re.compile(r"\[\[mock:sleep:(\d+(?:\.\d+)?)\]\]")
# [[mock:tools]][["fs_write", {"path": "a", "content": "b"}], ["fs_read", {"path": "a"}]]
#   [[/mock:tools]]
# → one tool call per turn, then a final answer that quotes the last tool result.
_TOOLS_RE = re.compile(r"\[\[mock:tools\]\](.*?)\[\[/mock:tools\]\]", re.DOTALL)

# Handlers registered by other modules (e.g. the orchestrator) to script replies.
ScriptedHandler = Callable[[ChatRequest], ChatResult | None]
_handlers: list[ScriptedHandler] = []


def register_scripted_handler(handler: ScriptedHandler) -> None:
    if handler not in _handlers:
        _handlers.append(handler)


def last_user_text(req: ChatRequest) -> str:
    for m in reversed(req.messages):
        if m.role == "user":
            return m.content
    return ""


def _count_words(text: str) -> int:
    return len(text.split())


def _scripted_tools(req: ChatRequest) -> ChatResult | None:
    first = next((m.content for m in req.messages if m.role == "user"), "")
    match = _TOOLS_RE.search(first)
    if not match:
        return None
    try:
        steps = [(str(name), dict(args)) for name, args in json.loads(match.group(1))]
    except (ValueError, TypeError):
        return ChatResult(text="Mock: invalid [[mock:tools]] script.")
    turn = sum(1 for m in req.messages if m.role == "assistant")
    if turn < len(steps):
        name, args = steps[turn]
        return ChatResult(text="", tool_calls=(ToolCall(f"mock_{turn}", name, args),))
    results = [m.content for m in req.messages if m.role == "tool"]
    return ChatResult(
        text="Mock done. Last tool result:\n" + (results[-1] if results else "(none)")
    )


class MockProvider:
    name = "mock"

    def __init__(self, *, chunk_delay: float = 0.01) -> None:
        self.chunk_delay = chunk_delay

    async def aclose(self) -> None:
        return None

    async def list_models(self) -> list[ModelInfo]:
        return list(MOCK_MODELS)

    def _reply(self, req: ChatRequest) -> ChatResult:
        text = last_user_text(req)
        match = _ERROR_RE.search(text)
        if match:
            kind = match.group(1)
            raise ProviderError(
                cast(ErrorKind, kind if kind in ERROR_MESSAGES else "unknown"), provider="mock"
            )
        for handler in _handlers:
            scripted = handler(req)
            if scripted is not None:
                return scripted
        tools = _scripted_tools(req)
        if tools is not None:
            return tools
        reply = f"Echo: {text.replace('[[mock:slow]]', '').strip()}"
        usage = Usage(
            input_tokens=sum(_count_words(m.content) for m in req.messages),
            output_tokens=_count_words(reply),
        )
        return ChatResult(text=reply, usage=usage, stop_reason="end_turn", model=req.model)

    async def complete(self, req: ChatRequest) -> ChatResult:
        user_text = " ".join(m.content for m in req.messages if m.role == "user")
        sleep = _SLEEP_RE.search(user_text)
        if sleep:
            await asyncio.sleep(min(float(sleep.group(1)), 60.0))
        elif "[[mock:slow]]" in user_text:
            await asyncio.sleep(3.0)  # lets tests observe a running agent
        return self._reply(req)

    async def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        result = self._reply(req)
        delay = 0.25 if "[[mock:slow]]" in last_user_text(req) else self.chunk_delay
        words = result.text.split(" ")
        for i, word in enumerate(words):
            await asyncio.sleep(delay)
            yield ChatChunk(text=word if i == 0 else " " + word)
        yield ChatChunk(result=result)
