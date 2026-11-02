from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import CurrentAuth, DbSession, SettingsDep
from app.services.push import PushService

router = APIRouter(prefix="/push", tags=["notifications"])


class PushKey(BaseModel):
    public_key: str


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=10, max_length=200)
    auth: str = Field(min_length=10, max_length=100)


class SubscriptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str = Field(min_length=10, max_length=1000)
    keys: SubscriptionKeys
    kinds: list[str] = Field(
        default_factory=lambda: ["approval", "taskDone", "taskFailed", "budget"], max_length=10
    )
    locale: str = Field(default="ru", max_length=8)
    label: str = Field(default="", max_length=200)


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    kinds: list[str]
    locale: str
    created_at: datetime
    last_sent_at: datetime | None


@router.get("/key", response_model=PushKey, summary="VAPID public key for PushManager.subscribe")
async def push_key(ctx: CurrentAuth, db: DbSession, settings: SettingsDep) -> PushKey:
    return PushKey(public_key=await PushService(db, settings).public_key(ctx.user.id))


@router.get("/subscriptions", response_model=list[SubscriptionOut])
async def list_subscriptions(
    ctx: CurrentAuth, db: DbSession, settings: SettingsDep
) -> list[SubscriptionOut]:
    rows = await PushService(db, settings).list_subscriptions(ctx.user.id)
    return [SubscriptionOut.model_validate(r) for r in rows]


@router.post("/subscriptions", response_model=SubscriptionOut, summary="Add or update this device")
async def subscribe(
    body: SubscriptionIn, ctx: CurrentAuth, db: DbSession, settings: SettingsDep
) -> SubscriptionOut:
    row = await PushService(db, settings).subscribe(
        ctx.user.id,
        endpoint=body.endpoint,
        p256dh=body.keys.p256dh,
        auth=body.keys.auth,
        kinds=body.kinds,
        locale=body.locale,
        label=body.label,
    )
    return SubscriptionOut.model_validate(row)


@router.delete("/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    endpoint: str = Query(..., max_length=1000),
) -> Response:
    await PushService(db, settings).unsubscribe(ctx.user.id, endpoint)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
