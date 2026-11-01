"""Voice input and semantic search use the owner's own provider (official API key, spec
13.5): an OpenAI-type provider chosen in Settings → Voice & search (or the first enabled
one). Anthropic has no speech or embedding API, so it cannot serve these.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.provider import Provider
from app.models.system import SystemSetting
from app.models.usage import UsageRecord
from app.providers.gateway import ModelGateway
from app.providers.registry import env_api_key

SETTINGS_KEY = "ai_services"
CAPABLE_KINDS = ("openai", "mock")


class AiServiceUnavailable(AppError):
    status_code = 409
    code = "ai_service_unavailable"
    message = "Voice and smart search need an OpenAI provider (Settings → AI providers)."


class AuxProvider(Protocol):
    async def transcribe(
        self, audio: bytes, filename: str, model: str, language: str | None = None
    ) -> str: ...

    async def embed(
        self, texts: list[str], model: str, dimensions: int | None = None
    ) -> tuple[list[list[float]], int | None]: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True)
class AuxTarget:
    provider_id: uuid.UUID
    kind: str
    name: str
    base_url: str | None
    transcription_model: str
    embedding_model: str
    embedding_dimensions: int
    semantic_search: bool
    api_key: str | None = field(default=None, repr=False)


async def load_settings(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    row = (
        await db.execute(
            select(SystemSetting).where(
                SystemSetting.user_id == user_id, SystemSetting.key == SETTINGS_KEY
            )
        )
    ).scalar_one_or_none()
    return dict(row.value or {}) if row else {}


async def save_settings(db: AsyncSession, user_id: uuid.UUID, value: dict[str, Any]) -> None:
    row = (
        await db.execute(
            select(SystemSetting)
            .where(SystemSetting.user_id == user_id, SystemSetting.key == SETTINGS_KEY)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(SystemSetting(user_id=user_id, key=SETTINGS_KEY, value=value))
    else:
        row.value = value


async def resolve(
    db: AsyncSession, gateway: ModelGateway, settings: Settings, user_id: uuid.UUID
) -> AuxTarget:
    chosen = await load_settings(db, user_id)
    query = select(Provider).where(
        Provider.user_id == user_id,
        Provider.enabled.is_(True),
        Provider.kind.in_(CAPABLE_KINDS),
    )
    provider = None
    if chosen.get("provider_id"):
        provider = (
            await db.execute(query.where(Provider.id == uuid.UUID(chosen["provider_id"])))
        ).scalar_one_or_none()
    if provider is None:  # the first suitable provider (real ones before the mock)
        rows = list((await db.execute(query.order_by(Provider.created_at))).scalars())
        provider = next((p for p in rows if p.kind != "mock"), rows[0] if rows else None)
    if provider is None:
        raise AiServiceUnavailable()
    api_key = (
        gateway.secrets.decrypt(provider.api_key_encrypted)
        if provider.api_key_encrypted
        else env_api_key(provider.kind, settings)
    )
    return AuxTarget(
        provider_id=provider.id,
        kind=provider.kind,
        name=provider.name,
        base_url=provider.base_url,
        transcription_model=chosen.get("transcription_model") or settings.transcription_model,
        embedding_model=chosen.get("embedding_model") or settings.embedding_model,
        embedding_dimensions=int(
            chosen.get("embedding_dimensions") or settings.embedding_dimensions
        ),
        semantic_search=bool(chosen.get("semantic_search", True)),
        api_key=api_key,
    )


def adapter(gateway: ModelGateway, target: AuxTarget) -> AuxProvider:
    return gateway.adapter(target.kind, target.api_key, target.base_url)  # type: ignore[return-value]


def ledger_row(
    user_id: uuid.UUID, target: AuxTarget, source: str, model: str, tokens: int | None
) -> UsageRecord:
    """Voice and embedding calls are listed in Costs (no token prices: cost unknown)."""
    return UsageRecord(
        user_id=user_id,
        source=source,
        provider_kind=target.kind,
        model=model,
        input_tokens=tokens or 0,
        output_tokens=0,
        cost_usd=None,
    )


async def transcribe(
    db: AsyncSession,
    gateway: ModelGateway,
    settings: Settings,
    user_id: uuid.UUID,
    audio: bytes,
    filename: str,
    language: str | None,
) -> str:
    from app.services.usage import ensure_within_budget

    target = await resolve(db, gateway, settings, user_id)
    await ensure_within_budget(db, user_id)
    client = adapter(gateway, target)
    try:
        text = await client.transcribe(audio, filename, target.transcription_model, language)
    finally:
        await client.aclose()
    db.add(ledger_row(user_id, target, "voice", target.transcription_model, None))
    await db.commit()
    return text.strip()
