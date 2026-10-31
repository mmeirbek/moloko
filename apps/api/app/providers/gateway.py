"""Model Gateway: the single entry point the rest of the app uses to call models.

* resolves which provider/model to use (per conversation or per agent),
* decrypts credentials just-in-time (never logged, never returned to clients),
* bounded retries with exponential backoff for retryable errors — before the first
  streamed token only (a half-streamed answer is never silently restarted),
* token usage and approximate cost (when the owner entered prices).
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.crypto import SecretBox
from app.core.errors import AppError
from app.models.provider import ModelConfig, Provider
from app.providers.base import (
    ChatChunk,
    ChatRequest,
    ChatResult,
    ModelProvider,
    ProviderError,
    Usage,
)
from app.providers.registry import build_provider, env_api_key

logger = logging.getLogger("moloko.gateway")

# Provider error texts sometimes echo (partially masked) keys; never let them reach logs.
_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-*.]{6,}|[A-Za-z0-9_\-]{32,})")


def redact(text: str) -> str:
    return _SECRET_RE.sub("[redacted]", text)


T = TypeVar("T")
ProviderFactory = Callable[..., ModelProvider]


class NoModelConfigured(AppError):
    status_code = 409
    code = "no_model_configured"
    message = "No AI model is available. Add a provider and enable a model in Settings."


class ModelUnavailable(AppError):
    status_code = 409
    code = "model_unavailable"
    message = "The selected model is disabled or its provider is turned off."


@dataclass(frozen=True)
class ModelTarget:
    """Everything needed to call one model. ``api_key`` is excluded from repr/logs."""

    model_config_id: uuid.UUID
    provider_id: uuid.UUID
    provider_kind: str
    provider_name: str
    model: str
    base_url: str | None
    input_price_per_mtok: Decimal | None
    output_price_per_mtok: Decimal | None
    params: dict[str, Any]
    api_key: str | None = field(default=None, repr=False)


def estimate_cost(target: ModelTarget, usage: Usage) -> Decimal | None:
    if target.input_price_per_mtok is None or target.output_price_per_mtok is None:
        return None
    if usage.input_tokens is None or usage.output_tokens is None:
        return None
    million = Decimal(1_000_000)
    return (
        Decimal(usage.input_tokens) * target.input_price_per_mtok / million
        + Decimal(usage.output_tokens) * target.output_price_per_mtok / million
    ).quantize(Decimal("0.000001"))


class ModelGateway:
    def __init__(
        self,
        settings: Settings,
        *,
        provider_factory: ProviderFactory = build_provider,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.settings = settings
        self.secrets = SecretBox(
            settings.app_encryption_key.get_secret_value() if settings.app_encryption_key else None
        )
        self._factory = provider_factory
        self._sleep = sleep

    # --- resolution ------------------------------------------------------------

    async def resolve(
        self, db: AsyncSession, user_id: uuid.UUID, model_config_id: uuid.UUID | None
    ) -> ModelTarget:
        """Pick the requested model, else the default, else the first enabled one."""
        query = (
            select(ModelConfig)
            .join(Provider, ModelConfig.provider_id == Provider.id)
            .where(ModelConfig.user_id == user_id)
        )
        if model_config_id is not None:
            config = (
                await db.execute(query.where(ModelConfig.id == model_config_id))
            ).scalar_one_or_none()
            if config is None:
                raise ModelUnavailable("The selected model no longer exists.")
            if not config.enabled or not config.provider.enabled:
                raise ModelUnavailable()
        else:
            usable = query.where(ModelConfig.enabled.is_(True), Provider.enabled.is_(True))
            config = (
                await db.execute(
                    usable.order_by(ModelConfig.is_default.desc(), ModelConfig.created_at).limit(1)
                )
            ).scalar_one_or_none()
            if config is None:
                raise NoModelConfigured()
        return self.target_for(config)

    def target_for(self, config: ModelConfig) -> ModelTarget:
        provider = config.provider
        api_key = (
            self.secrets.decrypt(provider.api_key_encrypted)
            if provider.api_key_encrypted
            else env_api_key(provider.kind, self.settings)
        )
        return ModelTarget(
            model_config_id=config.id,
            provider_id=provider.id,
            provider_kind=provider.kind,
            provider_name=provider.name,
            model=config.model,
            base_url=provider.base_url,
            input_price_per_mtok=config.input_price_per_mtok,
            output_price_per_mtok=config.output_price_per_mtok,
            params=dict(config.params or {}),
            api_key=api_key,
        )

    def adapter(self, kind: str, api_key: str | None, base_url: str | None) -> ModelProvider:
        return self._factory(kind, api_key=api_key, base_url=base_url, settings=self.settings)

    def _adapter_for(self, target: ModelTarget) -> ModelProvider:
        return self.adapter(target.provider_kind, target.api_key, target.base_url)

    def with_defaults(self, target: ModelTarget, req: ChatRequest) -> ChatRequest:
        max_tokens = (
            req.max_tokens
            or target.params.get("max_tokens")
            or self.settings.chat_max_output_tokens
        )
        temperature = (
            req.temperature if req.temperature is not None else target.params.get("temperature")
        )
        return ChatRequest(
            model=target.model,
            messages=req.messages,
            system=req.system,
            max_tokens=int(max_tokens),
            temperature=temperature,
            tools=req.tools,
        )

    # --- calls -----------------------------------------------------------------

    async def _backoff(self, attempt: int) -> None:
        base = self.settings.provider_retry_base_delay_seconds
        await self._sleep(base * (2**attempt) * (0.5 + random.random() / 2))  # noqa: S311

    async def _with_retries(self, target: ModelTarget, call: Callable[[], Awaitable[T]]) -> T:
        attempt = 0
        while True:
            try:
                return await call()
            except ProviderError as exc:
                self._log_error(target, exc, attempt)
                if not exc.retryable or attempt >= self.settings.provider_max_retries:
                    raise
            await self._backoff(attempt)
            attempt += 1

    async def complete(self, target: ModelTarget, req: ChatRequest) -> ChatResult:
        request = self.with_defaults(target, req)

        async def call() -> ChatResult:
            adapter = self._adapter_for(target)
            try:
                return await adapter.complete(request)
            finally:
                await adapter.aclose()

        return await self._with_retries(target, call)

    async def stream(self, target: ModelTarget, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        request = self.with_defaults(target, req)
        attempt = 0
        while True:
            adapter = self._adapter_for(target)
            started = False
            try:
                async for chunk in adapter.stream(request):
                    started = True
                    yield chunk
                return
            except ProviderError as exc:
                self._log_error(target, exc, attempt)
                if started or not exc.retryable or attempt >= self.settings.provider_max_retries:
                    raise
            finally:
                await adapter.aclose()
            await self._backoff(attempt)
            attempt += 1

    async def list_models(self, kind: str, api_key: str | None, base_url: str | None) -> list[Any]:
        adapter = self.adapter(kind, api_key, base_url)
        try:
            return await adapter.list_models()
        finally:
            await adapter.aclose()

    def _log_error(self, target: ModelTarget, exc: ProviderError, attempt: int) -> None:
        logger.warning(
            "provider_error",
            extra={
                "provider": target.provider_kind,
                "model": target.model,
                "kind": exc.kind,
                "attempt": attempt,
                "detail": redact(exc.detail or "")[:300],
            },
        )
