"""Provider kind ``codex``: the models of the owner's ChatGPT plan through Codex (service
`codex`). They run agents' tasks (runtimes/codex_run.py), not chat answers: a chat request is
refused, so neither the chat nor the Orchestrator's own planning uses them."""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.codex.client import CodexClient
from app.core.config import Settings
from app.providers.base import ChatChunk, ChatRequest, ChatResult, ModelInfo, ProviderError


class CodexProvider:
    name = "codex"

    def __init__(self, settings: Settings) -> None:
        self._client = CodexClient(settings)

    async def list_models(self) -> list[ModelInfo]:
        return await self._client.models()

    async def complete(self, req: ChatRequest) -> ChatResult:
        raise ProviderError(
            "bad_request", "Codex models do agents' tasks, not chat answers", provider="codex"
        )

    async def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        raise ProviderError(
            "bad_request", "Codex models do agents' tasks, not chat answers", provider="codex"
        )
        yield  # pragma: no cover — makes this an async generator

    async def aclose(self) -> None:
        return None
