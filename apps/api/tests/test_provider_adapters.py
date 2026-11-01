"""Adapters against the real official SDKs, with HTTP mocked at the transport level."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import ChatMessage, ChatRequest, ProviderError, ToolCall, ToolSpec
from app.providers.openai_provider import OpenAIProvider

Handler = Callable[[httpx2.Request], httpx2.Response]


def mock_client(handler: Handler) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


def sse(events: list[tuple[str | None, Any]]) -> bytes:
    out = []
    for name, data in events:
        payload = data if isinstance(data, str) else json.dumps(data)
        out.append((f"event: {name}\n" if name else "") + f"data: {payload}\n\n")
    return "".join(out).encode()


TOOL = ToolSpec(
    "get_weather",
    "Weather for a city",
    {"type": "object", "properties": {"city": {"type": "string"}}},
)


# --- OpenAI ------------------------------------------------------------------------


def openai_completion(**message: Any) -> dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "gpt-test",
        "choices": [
            {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", **message}}
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }


async def test_openai_complete_maps_request_and_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "https://attacker.example/v1")
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["auth"] = request.headers["authorization"]
        seen["url"] = str(request.url)
        seen["host"] = request.url.host
        seen["body"] = json.loads(request.content)
        return httpx2.Response(
            200,
            json=openai_completion(
                content=None,
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"city": "Almaty"}'},
                    }
                ],
            ),
        )

    provider = OpenAIProvider("sk-test-key", http_client=mock_client(handler))
    result = await provider.complete(
        ChatRequest(
            model="gpt-test",
            system="Be brief.",
            max_tokens=100,
            messages=(
                ChatMessage(role="user", content="Weather?"),
                ChatMessage(
                    role="assistant", tool_calls=(ToolCall("call_0", "get_weather", {"city": "X"}),)
                ),
                ChatMessage(role="tool", content="sunny", tool_call_id="call_0"),
            ),
            tools=(TOOL,),
        )
    )
    await provider.aclose()

    assert seen["auth"] == "Bearer sk-test-key"
    assert seen["host"] == "api.openai.com"
    assert seen["url"].endswith("/chat/completions")
    body = seen["body"]
    assert body["model"] == "gpt-test"
    assert body["max_completion_tokens"] == 100
    assert body["messages"][0] == {"role": "system", "content": "Be brief."}
    assert body["messages"][2]["tool_calls"][0]["function"]["arguments"] == '{"city": "X"}'
    assert body["messages"][3] == {"role": "tool", "tool_call_id": "call_0", "content": "sunny"}
    assert body["tools"][0]["function"]["name"] == "get_weather"

    assert result.tool_calls == (ToolCall("call_1", "get_weather", {"city": "Almaty"}),)
    assert result.usage.input_tokens == 11 and result.usage.output_tokens == 7


async def test_openai_stream_yields_deltas_and_usage() -> None:
    def chunk(content: str | None, finish: str | None = None, usage: Any = None) -> dict[str, Any]:
        choices = (
            []
            if content is None and finish is None
            else [
                {
                    "index": 0,
                    "delta": {"content": content} if content else {},
                    "finish_reason": finish,
                }
            ]
        )
        return {
            "id": "c",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "gpt-test",
            "choices": choices,
            "usage": usage,
        }

    body = sse(
        [
            (None, chunk("Hel")),
            (None, chunk("lo")),
            (None, chunk(None, "stop")),
            (
                None,
                chunk(None, usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}),
            ),
            (None, "[DONE]"),
        ]
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert json.loads(request.content)["stream_options"] == {"include_usage": True}
        return httpx2.Response(200, content=body, headers={"content-type": "text/event-stream"})

    provider = OpenAIProvider("sk-x", http_client=mock_client(handler))
    chunks = [
        c
        async for c in provider.stream(
            ChatRequest(model="gpt-test", messages=(ChatMessage("user", "hi"),))
        )
    ]
    await provider.aclose()
    assert [c.text for c in chunks if c.text] == ["Hel", "lo"]
    final = chunks[-1].result
    assert final is not None and final.text == "Hello"
    assert final.usage.output_tokens == 2 and final.stop_reason == "stop"


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (401, "auth_failed"),
        (403, "auth_failed"),
        (404, "model_not_found"),
        (429, "rate_limited"),
        (500, "unavailable"),
        (503, "unavailable"),
        (400, "bad_request"),
    ],
)
async def test_openai_errors_are_normalised(status: int, kind: str) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json={"error": {"message": "nope", "type": "x"}})

    provider = OpenAIProvider("sk-x", http_client=mock_client(handler))
    with pytest.raises(ProviderError) as info:
        await provider.complete(ChatRequest(model="m", messages=(ChatMessage("user", "hi"),)))
    await provider.aclose()
    assert info.value.kind == kind
    assert info.value.retryable == (kind in {"rate_limited", "unavailable", "timeout"})


async def test_openai_connection_error_is_unavailable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    provider = OpenAIProvider("sk-x", http_client=mock_client(handler))
    with pytest.raises(ProviderError) as info:
        await provider.complete(ChatRequest(model="m", messages=(ChatMessage("user", "hi"),)))
    await provider.aclose()
    assert info.value.kind == "unavailable"


async def test_openai_list_models() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path.endswith("/models")
        return httpx2.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"id": "b-model", "object": "model", "created": 1, "owned_by": "x"},
                    {"id": "a-model", "object": "model", "created": 1, "owned_by": "x"},
                ],
            },
        )

    provider = OpenAIProvider("sk-x", http_client=mock_client(handler))
    models = await provider.list_models()
    await provider.aclose()
    assert [m.id for m in models] == ["a-model", "b-model"]


# --- Anthropic -----------------------------------------------------------------------


async def test_anthropic_complete_maps_system_tools_and_tool_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://attacker.example")
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["auth"] = request.headers["authorization"]
        seen["host"] = request.url.host
        seen["body"] = json.loads(request.content)
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-test",
                "content": [
                    {"type": "text", "text": "Checking."},
                    {
                        "type": "tool_use",
                        "id": "tu_1",
                        "name": "get_weather",
                        "input": {"city": "Astana"},
                    },
                ],
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "usage": {"input_tokens": 20, "output_tokens": 5},
            },
        )

    provider = AnthropicProvider("sk-ant-test", http_client=mock_client(handler))
    result = await provider.complete(
        ChatRequest(
            model="claude-test",
            system="You are helpful.",
            max_tokens=256,
            messages=(
                ChatMessage("user", "Weather in two cities?"),
                ChatMessage(
                    "assistant",
                    tool_calls=(
                        ToolCall("t1", "get_weather", {"city": "A"}),
                        ToolCall("t2", "get_weather", {"city": "B"}),
                    ),
                ),
                ChatMessage("tool", "sunny", tool_call_id="t1"),
                ChatMessage("tool", "boom", tool_call_id="t2", is_error=True),
            ),
            tools=(TOOL,),
        )
    )
    await provider.aclose()

    assert seen["auth"] == "Bearer sk-ant-test"
    # Even with ANTHROPIC_BASE_URL set in the environment, the official host is used.
    assert seen["host"] == "api.anthropic.com"
    body = seen["body"]
    assert body["system"] == "You are helpful."
    assert body["max_tokens"] == 256
    assert body["tools"][0]["input_schema"]["properties"]["city"]["type"] == "string"
    # Both tool results are merged into one user turn, as the API requires.
    assert len(body["messages"]) == 3
    results = body["messages"][2]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert results[1]["is_error"] is True

    assert result.text == "Checking."
    assert result.tool_calls == (ToolCall("tu_1", "get_weather", {"city": "Astana"}),)
    assert result.usage.input_tokens == 20


async def test_anthropic_stream_parses_events() -> None:
    body = sse(
        [
            (
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": "m",
                        "type": "message",
                        "role": "assistant",
                        "model": "claude-test",
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {"input_tokens": 9, "output_tokens": 1},
                    },
                },
            ),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "Сәлем"},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "!"},
                },
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": 4},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        ]
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx2.Response(200, content=body, headers={"content-type": "text/event-stream"})

    provider = AnthropicProvider("sk-ant", http_client=mock_client(handler))
    chunks = [
        c
        async for c in provider.stream(
            ChatRequest(model="claude-test", messages=(ChatMessage("user", "hi"),))
        )
    ]
    await provider.aclose()
    assert "".join(c.text for c in chunks) == "Сәлем!"
    final = chunks[-1].result
    assert final is not None
    assert (final.usage.input_tokens, final.usage.output_tokens) == (9, 4)
    assert final.stop_reason == "end_turn"


@pytest.mark.parametrize(
    ("status", "kind"), [(401, "auth_failed"), (429, "rate_limited"), (529, "unavailable")]
)
async def test_anthropic_errors_are_normalised(status: int, kind: str) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            status, json={"type": "error", "error": {"type": "x", "message": "nope"}}
        )

    provider = AnthropicProvider("sk-ant", http_client=mock_client(handler))
    with pytest.raises(ProviderError) as info:
        await provider.complete(ChatRequest(model="m", messages=(ChatMessage("user", "hi"),)))
    await provider.aclose()
    assert info.value.kind == kind
