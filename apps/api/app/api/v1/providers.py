from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentAuth, DbSession, GatewayDep, SettingsDep
from app.providers.registry import available_kinds
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
from app.services.providers import ProviderService, model_out, provider_out

router = APIRouter(tags=["models"])


@router.get(
    "/providers/kinds", response_model=list[str], summary="Provider types this server supports"
)
async def provider_kinds(settings: SettingsDep) -> list[str]:
    return list(available_kinds(settings))


@router.get("/providers", response_model=list[ProviderOut])
async def list_providers(
    ctx: CurrentAuth, db: DbSession, settings: SettingsDep, gateway: GatewayDep
) -> list[ProviderOut]:
    rows = await ProviderService(db, settings, gateway).list_providers(ctx.user.id)
    return [provider_out(p, settings) for p in rows]


@router.post("/providers", response_model=ProviderOut, status_code=status.HTTP_201_CREATED)
async def create_provider(
    body: ProviderCreate,
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    gateway: GatewayDep,
) -> ProviderOut:
    provider = await ProviderService(db, settings, gateway).create(ctx.user.id, body)
    return provider_out(provider, settings)


@router.patch("/providers/{provider_id}", response_model=ProviderOut)
async def update_provider(
    provider_id: uuid.UUID,
    body: ProviderUpdate,
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    gateway: GatewayDep,
) -> ProviderOut:
    provider = await ProviderService(db, settings, gateway).update(ctx.user.id, provider_id, body)
    return provider_out(provider, settings)


@router.post(
    "/providers/{provider_id}/test", response_model=ProviderTestResult, summary="Check credentials"
)
async def test_provider(
    provider_id: uuid.UUID,
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    gateway: GatewayDep,
) -> ProviderTestResult:
    return await ProviderService(db, settings, gateway).test(ctx.user.id, provider_id)


@router.post(
    "/providers/{provider_id}/sync-models",
    response_model=SyncModelsResult,
    summary="Import the provider's model list",
)
async def sync_models(
    provider_id: uuid.UUID,
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    gateway: GatewayDep,
) -> SyncModelsResult:
    return await ProviderService(db, settings, gateway).sync_models(ctx.user.id, provider_id)


@router.get("/models", response_model=list[ModelOut])
async def list_models(
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    gateway: GatewayDep,
    include_disabled: bool = Query(False),
) -> list[ModelOut]:
    rows = await ProviderService(db, settings, gateway).list_models(
        ctx.user.id, include_disabled=include_disabled
    )
    return [model_out(m) for m in rows]


@router.post("/models", response_model=ModelOut, status_code=status.HTTP_201_CREATED)
async def create_model(
    body: ModelCreate, ctx: CurrentAuth, db: DbSession, settings: SettingsDep, gateway: GatewayDep
) -> ModelOut:
    return model_out(await ProviderService(db, settings, gateway).create_model(ctx.user.id, body))


@router.patch("/models/{model_id}", response_model=ModelOut)
async def update_model(
    model_id: uuid.UUID,
    body: ModelUpdate,
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    gateway: GatewayDep,
) -> ModelOut:
    return model_out(
        await ProviderService(db, settings, gateway).update_model(ctx.user.id, model_id, body)
    )
