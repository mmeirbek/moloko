"""Builds provider adapters. The only place that knows which adapter serves which kind."""

from __future__ import annotations

from typing import Literal

import httpx2

from app.core.config import Settings
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import ModelProvider
from app.providers.codex_provider import CodexProvider
from app.providers.mock_provider import MockProvider
from app.providers.openai_provider import OpenAIProvider

ProviderKind = Literal["openai", "anthropic", "mock", "codex"]
PROVIDER_KINDS: tuple[ProviderKind, ...] = ("openai", "anthropic", "mock", "codex")


def available_kinds(settings: Settings) -> list[ProviderKind]:
    return [
        k
        for k in PROVIDER_KINDS
        if (k != "mock" or settings.enable_mock_provider) and (k != "codex" or settings.codex_url)
    ]


def env_api_key(kind: str, settings: Settings) -> str | None:
    secret = {"openai": settings.openai_api_key, "anthropic": settings.anthropic_api_key}.get(kind)
    return secret.get_secret_value() if secret else None


def build_provider(
    kind: str,
    *,
    api_key: str | None,
    base_url: str | None,
    settings: Settings,
    http_client: httpx2.AsyncClient | None = None,
) -> ModelProvider:
    timeout = settings.provider_timeout_seconds
    if kind == "mock":
        return MockProvider()
    if kind == "codex":  # signed in with ChatGPT inside the codex service: no API key here
        return CodexProvider(settings)
    if not api_key:
        from app.providers.base import ProviderError

        raise ProviderError("auth_failed", "no API key configured", provider=kind)
    if kind == "openai":
        return OpenAIProvider(api_key, base_url=base_url, timeout=timeout, http_client=http_client)
    if kind == "anthropic":
        return AnthropicProvider(
            api_key, base_url=base_url, timeout=timeout, http_client=http_client
        )
    raise ValueError(f"unknown provider kind: {kind}")
