"""Anthropic adapter (official SDK, API-key auth only). Uses the Messages API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import anthropic
import httpx2

from app.providers.base import (
    ChatChunk,
    ChatMessage,
    ChatRequest,
    ChatResult,
    ModelInfo,
    ProviderError,
    ToolCall,
    Usage,
    error_kind_for_status,
)

# The Messages API requires max_tokens; the gateway always passes one, this is a last resort.
_FALLBACK_MAX_TOKENS = 4096


def _map_error(exc: Exception) -> ProviderError:
    if isinstance(exc, anthropic.APITimeoutError):
        return ProviderError("timeout", str(exc), provider="anthropic")
    if isinstance(exc, anthropic.APIConnectionError):
        return ProviderError("unavailable", str(exc), provider="anthropic")
    if isinstance(exc, anthropic.APIStatusError):
        kind = error_kind_for_status(exc.status_code)
        if exc.status_code == 529:  # overloaded
            kind = "unavailable"
        return ProviderError(kind, str(exc), provider="anthropic")
    return ProviderError("unknown", repr(exc), provider="anthropic")


def _content(m: ChatMessage) -> list[dict[str, Any]] | str:
    if m.role == "assistant" and m.tool_calls:
        blocks: list[dict[str, Any]] = []
        if m.content:
            blocks.append({"type": "text", "text": m.content})
        blocks += [
            {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments}
            for tc in m.tool_calls
        ]
        return blocks
    return m.content


def _messages(req: ChatRequest) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in req.messages:
        if m.role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": m.tool_call_id,
                "content": m.content,
                "is_error": m.is_error,
            }
            # Consecutive tool results must share one user turn.
            prev = out[-1] if out else None
            if (
                prev is not None
                and prev["role"] == "user"
                and isinstance(prev["content"], list)
                and all(b.get("type") == "tool_result" for b in prev["content"])
            ):
                prev["content"].append(block)
                continue
            out.append({"role": "user", "content": [block]})
        else:
            out.append({"role": m.role, "content": _content(m)})
    return out


def _kwargs(req: ChatRequest) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": req.model,
        "messages": _messages(req),
        "max_tokens": req.max_tokens or _FALLBACK_MAX_TOKENS,
    }
    if req.system:
        kwargs["system"] = req.system
    if req.temperature is not None:
        kwargs["temperature"] = req.temperature
    if req.tools:
        kwargs["tools"] = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in req.tools
        ]
    return kwargs


# Always passed explicitly: when base_url is None the SDK falls back to ANTHROPIC_BASE_URL
# (and profile files), which must never be able to redirect our API key elsewhere.
OFFICIAL_BASE_URL = "https://api.anthropic.com"


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str | None = None,
        timeout: float = 120.0,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            base_url=base_url or OFFICIAL_BASE_URL,
            timeout=timeout,
            max_retries=0,
            http_client=http_client,
        )

    async def aclose(self) -> None:
        await self._client.close()

    async def list_models(self) -> list[ModelInfo]:
        try:
            page = await self._client.models.list()
            models = [
                ModelInfo(id=m.id, display_name=getattr(m, "display_name", None))
                async for m in page
            ]
            return sorted(models, key=lambda m: m.id)
        except anthropic.AnthropicError as exc:
            raise _map_error(exc) from exc

    async def complete(self, req: ChatRequest) -> ChatResult:
        try:
            resp = await self._client.messages.create(**_kwargs(req))
        except anthropic.AnthropicError as exc:
            raise _map_error(exc) from exc
        texts: list[str] = []
        calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "tool_use":
                args = block.input if isinstance(block.input, dict) else {"_value": block.input}
                calls.append(ToolCall(id=block.id, name=block.name, arguments=args))
        return ChatResult(
            text="".join(texts),
            tool_calls=tuple(calls),
            usage=Usage(resp.usage.input_tokens, resp.usage.output_tokens),
            stop_reason=resp.stop_reason,
            model=resp.model,
        )

    async def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        if req.tools:
            result = await self.complete(req)
            if result.text:
                yield ChatChunk(text=result.text)
            yield ChatChunk(result=result)
            return
        parts: list[str] = []
        input_tokens: int | None = None
        output_tokens: int | None = None
        stop: str | None = None
        model: str | None = None
        try:
            stream = await self._client.messages.create(**_kwargs(req), stream=True)
            async for event in stream:
                if event.type == "message_start":
                    model = event.message.model
                    input_tokens = event.message.usage.input_tokens
                    output_tokens = event.message.usage.output_tokens
                elif event.type == "content_block_delta" and event.delta.type == "text_delta":
                    parts.append(event.delta.text)
                    yield ChatChunk(text=event.delta.text)
                elif event.type == "message_delta":
                    stop = event.delta.stop_reason or stop
                    if event.usage is not None and event.usage.output_tokens is not None:
                        output_tokens = event.usage.output_tokens
        except anthropic.AnthropicError as exc:
            raise _map_error(exc) from exc
        yield ChatChunk(
            result=ChatResult(
                text="".join(parts),
                usage=Usage(input_tokens, output_tokens),
                stop_reason=stop,
                model=model,
            )
        )
