"""Provider kind ``codex``: the models of the owner's ChatGPT plan through Codex (service
`codex`). Agents' tasks with these models run in the task's workspace (runtimes/codex_run.py);
a chat answer runs too (owner: «кодекс модели не работают» — the chat's default was a Codex
model): the conversation goes to Codex as one prompt in a scratch folder of its own, and its
reply streams back message by message (Codex streams whole messages, not tokens)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from app.codex.client import CodexClient
from app.core.config import Settings
from app.providers.base import ChatChunk, ChatRequest, ChatResult, ModelInfo, ProviderError, Usage

# Under the workspaces volume, which both the backend and the codex service mount.
CHAT_FOLDER = ".codex-chat"
# A chat answer does not wait long for an agent's Codex task to finish (one run at a time).
CHAT_WAIT_SECONDS = 90


def chat_prompt(req: ChatRequest) -> str:
    """The conversation as one prompt: Codex keeps no history of a chat between calls."""
    lines = [req.system.strip(), ""] if req.system else []
    lines.append(
        "Answer the owner's last message in this conversation as a helpful assistant. Do not "
        "change files unless the owner asks for it."
    )
    for m in req.messages:
        if m.role in ("user", "assistant") and m.content.strip():
            who = "Owner" if m.role == "user" else "You"
            note = " [attached a picture you cannot see here]" if m.images else ""
            lines.append(f"\n{who}:{note}\n{m.content.strip()}")
    return "\n".join(lines)


class CodexProvider:
    name = "codex"

    def __init__(self, settings: Settings) -> None:
        self._client = CodexClient(settings)
        self._folder = Path(settings.workspace_root) / CHAT_FOLDER

    async def list_models(self) -> list[ModelInfo]:
        return await self._client.models()

    async def complete(self, req: ChatRequest) -> ChatResult:
        result: ChatResult | None = None
        async for chunk in self.stream(req):
            result = chunk.result or result
        if result is None:
            raise ProviderError("unknown", "Codex gave no answer", provider="codex")
        return result

    async def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        # moloko's chat tools are not passed on: Codex has its own (search, commands)
        self._folder.mkdir(parents=True, exist_ok=True)
        texts: list[str] = []
        usage = Usage()
        completed = False
        async for event in self._client.run(
            cwd=CHAT_FOLDER,
            prompt=chat_prompt(req),
            model=req.model,
            thread_id=None,
            wait_seconds=CHAT_WAIT_SECONDS,
        ):
            kind = event.get("type")
            raw_item = event.get("item")
            item: dict[str, Any] = raw_item if isinstance(raw_item, dict) else {}
            if (
                kind == "item.completed"
                and item.get("type") == "agent_message"
                and item.get("text")
            ):
                text = str(item["text"])
                yield ChatChunk(text=("\n\n" if texts else "") + text)
                texts.append(text)
            elif kind == "turn.completed":
                completed = True
                raw = event.get("usage") or {}
                usage = Usage(
                    input_tokens=int(raw.get("input_tokens") or 0),
                    output_tokens=int(raw.get("output_tokens") or 0),
                )
            elif kind in ("turn.failed", "error"):
                from app.runtimes.codex_run import failure

                error = event.get("error") if kind == "turn.failed" else event
                raise failure(str((error or {}).get("message", "Codex failed")))
        if not completed and not texts:
            raise ProviderError("unavailable", "Codex stopped without an answer", provider="codex")
        yield ChatChunk(
            result=ChatResult(
                text="\n\n".join(texts), usage=usage, stop_reason="end_turn", model=req.model
            )
        )

    async def aclose(self) -> None:
        return None
