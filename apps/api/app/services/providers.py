"""AI provider accounts and the models the owner can pick (spec 13, Settings → AI Providers)."""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.crypto import secret_hint
from app.core.errors import AppError, Conflict, NotFound
from app.models.provider import ModelConfig, Provider
from app.providers.base import ProviderError
from app.providers.gateway import ModelGateway
from app.providers.registry import available_kinds, env_api_key
from app.schemas.providers import (
    ModelCreate,
    ModelOut,
    ModelUpdate,
    ProviderCreate,
    ProviderOut,
    ProviderTestResult,
    ProviderUpdate,
    SyncModelsResult,
)
from app.services.audit import AuditService


class ProviderKindUnavailable(AppError):
    status_code = 422
    code = "provider_kind_unavailable"
    message = "This provider type is not available on this server."


def provider_out(p: Provider, settings: Settings) -> ProviderOut:
    source: Literal["stored", "environment", "none"]
    if p.api_key_encrypted:
        source, hint = "stored", p.api_key_hint
    elif env_api_key(p.kind, settings) or p.kind == "mock":
        source, hint = "environment", None
    else:
        source, hint = "none", None
    return ProviderOut(
        id=p.id,
        kind=p.kind,
        name=p.name,
        base_url=p.base_url,
        enabled=p.enabled,
        api_key_source=source,
        api_key_hint=hint,
        created_at=p.created_at,
    )


def model_out(m: ModelConfig) -> ModelOut:
    return ModelOut(
        id=m.id,
        provider_id=m.provider_id,
        provider_name=m.provider.name,
        provider_kind=m.provider.kind,
        model=m.model,
        display_name=m.display_name,
        enabled=m.enabled,
        is_default=m.is_default,
        input_price_per_mtok=m.input_price_per_mtok,
        output_price_per_mtok=m.output_price_per_mtok,
        params=m.params or {},
    )


class ProviderService:
    def __init__(self, db: AsyncSession, settings: Settings, gateway: ModelGateway) -> None:
        self.db = db
        self.settings = settings
        self.gateway = gateway
        self.audit = AuditService(db)

    # --- providers ---------------------------------------------------------------

    async def _get(self, user_id: uuid.UUID, provider_id: uuid.UUID) -> Provider:
        provider = await self.db.get(Provider, provider_id)
        if provider is None or provider.user_id != user_id:
            raise NotFound("Provider not found.")
        return provider

    async def list_providers(self, user_id: uuid.UUID) -> list[Provider]:
        rows = await self.db.execute(
            select(Provider).where(Provider.user_id == user_id).order_by(Provider.created_at)
        )
        return list(rows.scalars())

    async def create(self, user_id: uuid.UUID, data: ProviderCreate) -> Provider:
        if data.kind not in available_kinds(self.settings):
            raise ProviderKindUnavailable()
        provider = Provider(
            user_id=user_id,
            kind=data.kind,
            name=data.name,
            base_url=data.base_url,
            enabled=data.enabled,
        )
        if data.api_key is not None and data.api_key.get_secret_value():
            key = data.api_key.get_secret_value()
            provider.api_key_encrypted = self.gateway.secrets.encrypt(key)
            provider.api_key_hint = secret_hint(key)
        self.db.add(provider)
        try:
            await self.db.flush()
        except IntegrityError:
            await self.db.rollback()
            raise Conflict("A provider with this name already exists.") from None
        await self.audit.record(
            "provider.created",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="provider",
            resource_id=str(provider.id),
            details={
                "kind": data.kind,
                "name": data.name,
                "api_key_stored": bool(provider.api_key_encrypted),
            },
        )
        await self.db.commit()
        return provider

    async def update(
        self, user_id: uuid.UUID, provider_id: uuid.UUID, data: ProviderUpdate
    ) -> Provider:
        provider = await self._get(user_id, provider_id)
        changed: dict[str, object] = {}
        if data.name is not None and data.name != provider.name:
            provider.name, changed["name"] = data.name, data.name
        if "base_url" in data.model_fields_set and data.base_url != provider.base_url:
            provider.base_url, changed["base_url"] = data.base_url, data.base_url
        if data.enabled is not None and data.enabled != provider.enabled:
            provider.enabled, changed["enabled"] = data.enabled, data.enabled
        if data.clear_api_key and provider.api_key_encrypted:
            provider.api_key_encrypted = provider.api_key_hint = None
            changed["api_key"] = "cleared"
        elif data.api_key is not None and data.api_key.get_secret_value():
            key = data.api_key.get_secret_value()
            provider.api_key_encrypted = self.gateway.secrets.encrypt(key)
            provider.api_key_hint = secret_hint(key)
            changed["api_key"] = "replaced"
        try:
            await self.db.flush()
        except IntegrityError:
            await self.db.rollback()
            raise Conflict("A provider with this name already exists.") from None
        if changed:
            await self.audit.record(
                "provider.updated",
                "success",
                actor_type="user",
                actor_id=user_id,
                user_id=user_id,
                resource_type="provider",
                resource_id=str(provider.id),
                details={"changed": changed},
            )
        await self.db.commit()
        return provider

    def _credentials(self, provider: Provider) -> str | None:
        if provider.api_key_encrypted:
            return self.gateway.secrets.decrypt(provider.api_key_encrypted)
        return env_api_key(provider.kind, self.settings)

    async def test(self, user_id: uuid.UUID, provider_id: uuid.UUID) -> ProviderTestResult:
        provider = await self._get(user_id, provider_id)
        try:
            models = await self.gateway.list_models(
                provider.kind, self._credentials(provider), provider.base_url
            )
        except ProviderError as exc:
            return ProviderTestResult(
                ok=False, error_code=f"provider_{exc.kind}", error_message=exc.message
            )
        return ProviderTestResult(ok=True, models_found=len(models))

    async def sync_models(self, user_id: uuid.UUID, provider_id: uuid.UUID) -> SyncModelsResult:
        provider = await self._get(user_id, provider_id)
        try:
            models = await self.gateway.list_models(
                provider.kind, self._credentials(provider), provider.base_url
            )
        except ProviderError as exc:
            raise AppError(exc.message, code=f"provider_{exc.kind}", status_code=502) from None
        existing = set(
            (
                await self.db.execute(
                    select(ModelConfig.model).where(ModelConfig.provider_id == provider.id)
                )
            ).scalars()
        )
        has_default = await self._has_default(user_id)
        added = 0
        for info in models:
            if info.id in existing:
                continue
            self.db.add(
                ModelConfig(
                    user_id=user_id,
                    provider_id=provider.id,
                    model=info.id,
                    display_name=info.display_name,
                    is_default=not has_default and added == 0,
                )
            )
            added += 1
        await self.audit.record(
            "provider.models_synced",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="provider",
            resource_id=str(provider.id),
            details={"added": added},
        )
        await self.db.commit()
        return SyncModelsResult(added=added, total=len(existing) + added)

    # --- models -------------------------------------------------------------------

    async def _has_default(self, user_id: uuid.UUID) -> bool:
        row = await self.db.execute(
            select(ModelConfig.id)
            .where(ModelConfig.user_id == user_id, ModelConfig.is_default.is_(True))
            .limit(1)
        )
        return row.first() is not None

    async def list_models(self, user_id: uuid.UUID, *, include_disabled: bool) -> list[ModelConfig]:
        query = (
            select(ModelConfig)
            .join(Provider, ModelConfig.provider_id == Provider.id)
            .where(ModelConfig.user_id == user_id)
            .order_by(Provider.name, ModelConfig.model)
        )
        if not include_disabled:
            query = query.where(ModelConfig.enabled.is_(True), Provider.enabled.is_(True))
        return list((await self.db.execute(query)).scalars())

    async def _get_model(self, user_id: uuid.UUID, model_id: uuid.UUID) -> ModelConfig:
        model = await self.db.get(ModelConfig, model_id)
        if model is None or model.user_id != user_id:
            raise NotFound("Model not found.")
        return model

    async def create_model(self, user_id: uuid.UUID, data: ModelCreate) -> ModelConfig:
        provider = await self._get(user_id, data.provider_id)
        model = ModelConfig(
            user_id=user_id,
            provider_id=provider.id,
            model=data.model.strip(),
            display_name=data.display_name,
            is_default=not await self._has_default(user_id),
            params={},
        )
        model.provider = provider  # loaded now: async sessions cannot lazy-load later
        self.db.add(model)
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise Conflict("This model is already added for this provider.") from None
        return model

    async def update_model(
        self, user_id: uuid.UUID, model_id: uuid.UUID, data: ModelUpdate
    ) -> ModelConfig:
        model = await self._get_model(user_id, model_id)
        fields = data.model_fields_set
        if "display_name" in fields:
            model.display_name = data.display_name
        if data.enabled is not None:
            model.enabled = data.enabled
        if "input_price_per_mtok" in fields:
            model.input_price_per_mtok = data.input_price_per_mtok
        if "output_price_per_mtok" in fields:
            model.output_price_per_mtok = data.output_price_per_mtok
        if data.params is not None:
            model.params = data.params.model_dump(exclude_none=True)
        if data.is_default:
            await self.db.execute(
                update(ModelConfig).where(ModelConfig.user_id == user_id).values(is_default=False)
            )
            model.is_default = True
        elif data.is_default is False:
            model.is_default = False
        await self.db.commit()
        return model
