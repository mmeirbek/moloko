from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest

from app.providers.base import (
    ChatChunk,
    ChatMessage,
    ChatRequest,
    ChatResult,
    ModelInfo,
    ProviderError,
    Usage,
)
from app.providers.gateway import ModelGateway, ModelTarget, estimate_cost, redact
from tests.conftest import make_settings


class FlakyProvider:
    """Fails with the given errors in order, then succeeds."""

    name = "flaky"

    def __init__(
        self, errors: list[ProviderError], *, fail_after_first_chunk: bool = False
    ) -> None:
        self.errors = errors
        self.calls = 0
        self.fail_after_first_chunk = fail_after_first_chunk

    async def aclose(self) -> None:
        return None

    async def list_models(self) -> list[ModelInfo]:
        return []

    async def complete(self, req: ChatRequest) -> ChatResult:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return ChatResult(text="ok", usage=Usage(10, 5))

    async def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        self.calls += 1
        if self.fail_after_first_chunk:
            yield ChatChunk(text="partial")
            raise ProviderError("unavailable")
        if self.errors:
            raise self.errors.pop(0)
        yield ChatChunk(text="ok")
        yield ChatChunk(result=ChatResult(text="ok"))


def target(**kw: Any) -> ModelTarget:
    base: dict[str, Any] = {
        "model_config_id": uuid.uuid4(),
        "provider_id": uuid.uuid4(),
        "provider_kind": "flaky",
        "provider_name": "Flaky",
        "model": "m",
        "base_url": None,
        "input_price_per_mtok": None,
        "output_price_per_mtok": None,
        "params": {},
        "api_key": "sk-secret",
    }
    base.update(kw)
    return ModelTarget(**base)


def gateway_with(provider: FlakyProvider, **settings: Any) -> tuple[ModelGateway, list[float]]:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    gw = ModelGateway(
        make_settings(provider_retry_base_delay_seconds=1.0, **settings),
        provider_factory=lambda *a, **k: provider,
        sleep=fake_sleep,
    )
    return gw, sleeps


REQ = ChatRequest(model="m", messages=(ChatMessage("user", "hi"),))


async def test_retries_retryable_errors_with_backoff() -> None:
    provider = FlakyProvider([ProviderError("rate_limited"), ProviderError("timeout")])
    gw, sleeps = gateway_with(provider, provider_max_retries=2)
    result = await gw.complete(target(), REQ)
    assert result.text == "ok"
    assert provider.calls == 3
    assert len(sleeps) == 2 and sleeps[1] > sleeps[0] * 0.9  # exponential


async def test_gives_up_after_max_retries() -> None:
    provider = FlakyProvider([ProviderError("unavailable")] * 5)
    gw, _ = gateway_with(provider, provider_max_retries=1)
    with pytest.raises(ProviderError) as info:
        await gw.complete(target(), REQ)
    assert info.value.kind == "unavailable"
    assert provider.calls == 2


@pytest.mark.parametrize("kind", ["auth_failed", "bad_request", "model_not_found"])
async def test_non_retryable_errors_fail_fast(kind: str) -> None:
    provider = FlakyProvider([ProviderError(kind)])  # type: ignore[arg-type]
    gw, sleeps = gateway_with(provider, provider_max_retries=3)
    with pytest.raises(ProviderError):
        await gw.complete(target(), REQ)
    assert provider.calls == 1 and sleeps == []


async def test_stream_retries_only_before_first_token() -> None:
    provider = FlakyProvider([ProviderError("rate_limited")])
    gw, _ = gateway_with(provider, provider_max_retries=2)
    chunks = [c async for c in gw.stream(target(), REQ)]
    assert [c.text for c in chunks if c.text] == ["ok"]
    assert provider.calls == 2

    half = FlakyProvider([], fail_after_first_chunk=True)
    gw, _ = gateway_with(half, provider_max_retries=3)
    received: list[str] = []
    with pytest.raises(ProviderError):
        async for chunk in gw.stream(target(), REQ):
            received.append(chunk.text)
    assert received == ["partial"]
    assert half.calls == 1  # never restarted a half-streamed answer


def test_cost_estimate_needs_prices_and_usage() -> None:
    assert estimate_cost(target(), Usage(1000, 500)) is None
    priced = target(input_price_per_mtok=Decimal("3"), output_price_per_mtok=Decimal("15"))
    assert estimate_cost(priced, Usage(1_000_000, 100_000)) == Decimal("4.500000")
    assert estimate_cost(priced, Usage(None, 5)) is None


def test_request_defaults_come_from_model_params_and_settings() -> None:
    gw, _ = gateway_with(FlakyProvider([]), chat_max_output_tokens=999)
    req = gw.with_defaults(target(params={"temperature": 0.2}), REQ)
    assert req.max_tokens == 999 and req.temperature == 0.2
    req = gw.with_defaults(target(params={"max_tokens": 50}), REQ)
    assert req.max_tokens == 50


def test_target_repr_never_contains_the_api_key() -> None:
    assert "sk-secret" not in repr(target())


def test_redact_masks_keys_in_error_text() -> None:
    text = "Incorrect API key provided: sk-proj-abc123def456ghi789. You can find..."
    assert "sk-proj-abc123" not in redact(text)
