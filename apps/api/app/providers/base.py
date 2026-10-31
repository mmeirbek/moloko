"""Provider-neutral request/response types and the ModelProvider contract."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, Protocol

Role = Literal["user", "assistant", "tool"]
ErrorKind = Literal[
    "auth_failed",
    "rate_limited",
    "timeout",
    "unavailable",
    "bad_request",
    "model_not_found",
    "cancelled",
    "unknown",
]


@dataclass(frozen=True)
class ModelInfo:
    id: str
    display_name: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()  # assistant asking to call tools
    tool_call_id: str | None = None  # role="tool": result for this call
    is_error: bool = False  # role="tool": the tool failed


@dataclass(frozen=True)
class ChatRequest:
    model: str
    messages: tuple[ChatMessage, ...]
    system: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    tools: tuple[ToolSpec, ...] = ()


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class ChatResult:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage = field(default_factory=Usage)
    stop_reason: str | None = None
    model: str | None = None


@dataclass(frozen=True)
class ChatChunk:
    """A streaming event: text deltas, then exactly one final chunk with ``result``."""

    text: str = ""
    result: ChatResult | None = None


ERROR_MESSAGES: dict[str, str] = {
    "auth_failed": "The provider rejected the API key. Check it in Settings → AI providers.",
    "rate_limited": "The provider is rate-limiting requests. Try again in a moment.",
    "timeout": "The provider did not answer in time.",
    "unavailable": "The provider is unavailable right now. Try again later.",
    "bad_request": "The provider rejected the request.",
    "model_not_found": "The provider does not know this model.",
    "cancelled": "The request was cancelled.",
    "unknown": "The provider request failed.",
}


class ProviderError(Exception):
    """A normalised provider failure. ``message`` is safe to show to the user."""

    RETRYABLE: ClassVar[frozenset[str]] = frozenset({"rate_limited", "timeout", "unavailable"})

    def __init__(
        self, kind: ErrorKind, detail: str | None = None, *, provider: str | None = None
    ) -> None:
        self.kind: ErrorKind = kind
        self.detail = detail  # technical; for logs only
        self.provider = provider
        super().__init__(ERROR_MESSAGES[kind])

    @property
    def message(self) -> str:
        return ERROR_MESSAGES[self.kind]

    @property
    def retryable(self) -> bool:
        return self.kind in self.RETRYABLE


def error_kind_for_status(status: int) -> ErrorKind:
    if status in (401, 403):
        return "auth_failed"
    if status == 404:
        return "model_not_found"
    if status == 408:
        return "timeout"
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "unavailable"
    return "bad_request"


class ModelProvider(Protocol):
    name: str

    async def list_models(self) -> list[ModelInfo]: ...

    async def complete(self, req: ChatRequest) -> ChatResult: ...

    def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]: ...

    async def aclose(self) -> None: ...
