"""OpenAI adapter (official SDK, API-key auth only). Uses the Chat Completions API."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx2
import openai

from app.providers.base import (
    ChatChunk,
    ChatRequest,
    ChatResult,
    ModelInfo,
    ProviderError,
    ToolCall,
    Usage,
    error_kind_for_status,
)


def _map_error(exc: Exception) -> ProviderError:
    if isinstance(exc, openai.APITimeoutError):
        return ProviderError("timeout", str(exc), provider="openai")
    if isinstance(exc, openai.APIConnectionError):
        return ProviderError("unavailable", str(exc), provider="openai")
    if isinstance(exc, openai.APIStatusError):
        return ProviderError(error_kind_for_status(exc.status_code), str(exc), provider="openai")
    return ProviderError("unknown", repr(exc), provider="openai")


def _messages(req: ChatRequest) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if req.system:
        out.append({"role": "system", "content": req.system})
    for m in req.messages:
        if m.role == "tool":
            out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
        elif m.role == "assistant" and m.tool_calls:
            out.append(
                {
                    "role": "assistant",
                    "content": m.content or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                        }
                        for tc in m.tool_calls
                    ],
                }
            )
        elif m.role == "user" and m.images:
            out.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": m.content},
                        *(
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{img.media_type};base64,{img.data_b64}"
                                },
                            }
                            for img in m.images
                        ),
                    ],
                }
            )
        else:
            out.append({"role": m.role, "content": m.content})
    return out


def _kwargs(req: ChatRequest) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"model": req.model, "messages": _messages(req)}
    if req.max_tokens is not None:
        kwargs["max_completion_tokens"] = req.max_tokens
    if req.temperature is not None:
        kwargs["temperature"] = req.temperature
    if req.tools:
        kwargs["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in req.tools
        ]
    return kwargs


def _parse_arguments(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}
    return value if isinstance(value, dict) else {"_value": value}


# Always passed explicitly: when base_url is None the SDK falls back to the OPENAI_BASE_URL
# environment variable, which must never be able to redirect our API key elsewhere.
OFFICIAL_BASE_URL = "https://api.openai.com/v1"


class OpenAIProvider:
    name = "openai"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str | None = None,
        timeout: float = 120.0,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        # Retries are handled by the gateway, so the SDK must not retry on its own.
        self._client = openai.AsyncOpenAI(
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
            models = [ModelInfo(id=m.id) async for m in page]
            return sorted(models, key=lambda m: m.id)
        except openai.OpenAIError as exc:
            raise _map_error(exc) from exc

    # --- voice and search (owner's OpenAI key; models come from settings) -----------------

    async def transcribe(
        self, audio: bytes, filename: str, model: str, language: str | None = None
    ) -> str:
        try:
            kwargs: dict[str, Any] = {"model": model, "file": (filename, audio)}
            if language:
                kwargs["language"] = language
            resp = await self._client.audio.transcriptions.create(**kwargs)
            return str(getattr(resp, "text", "") or "")
        except openai.OpenAIError as exc:
            raise _map_error(exc) from exc

    async def embed(
        self, texts: list[str], model: str, dimensions: int | None = None
    ) -> tuple[list[list[float]], int | None]:
        """Vectors for `texts` and the tokens used."""
        try:
            kwargs: dict[str, Any] = {"model": model, "input": texts}
            if dimensions:
                kwargs["dimensions"] = dimensions
            resp = await self._client.embeddings.create(**kwargs)
            vectors = [list(d.embedding) for d in sorted(resp.data, key=lambda d: d.index)]
            used = getattr(resp.usage, "total_tokens", None) if resp.usage else None
            return vectors, used
        except openai.OpenAIError as exc:
            raise _map_error(exc) from exc

    async def complete(self, req: ChatRequest) -> ChatResult:
        try:
            resp = await self._client.chat.completions.create(**_kwargs(req))
        except openai.OpenAIError as exc:
            raise _map_error(exc) from exc
        if not resp.choices:
            raise ProviderError("unknown", "empty choices", provider="openai")
        choice = resp.choices[0]
        calls = tuple(
            ToolCall(
                id=tc.id, name=tc.function.name, arguments=_parse_arguments(tc.function.arguments)
            )
            for tc in (choice.message.tool_calls or [])
            if getattr(tc, "function", None) is not None
        )
        usage = Usage(
            input_tokens=resp.usage.prompt_tokens if resp.usage else None,
            output_tokens=resp.usage.completion_tokens if resp.usage else None,
        )
        return ChatResult(
            text=choice.message.content or "",
            tool_calls=calls,
            usage=usage,
            stop_reason=choice.finish_reason,
            model=resp.model,
        )

    async def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        if req.tools:  # tool calling goes through complete(); keep streaming text-only
            result = await self.complete(req)
            if result.text:
                yield ChatChunk(text=result.text)
            yield ChatChunk(result=result)
            return
        parts: list[str] = []
        usage = Usage()
        finish: str | None = None
        model: str | None = None
        try:
            stream = await self._client.chat.completions.create(
                **_kwargs(req), stream=True, stream_options={"include_usage": True}
            )
            async for chunk in stream:
                model = chunk.model or model
                if chunk.usage is not None:
                    usage = Usage(chunk.usage.prompt_tokens, chunk.usage.completion_tokens)
                for choice in chunk.choices:
                    if choice.finish_reason:
                        finish = choice.finish_reason
                    delta = choice.delta.content if choice.delta else None
                    if delta:
                        parts.append(delta)
                        yield ChatChunk(text=delta)
        except openai.OpenAIError as exc:
            raise _map_error(exc) from exc
        yield ChatChunk(
            result=ChatResult(text="".join(parts), usage=usage, stop_reason=finish, model=model)
        )
