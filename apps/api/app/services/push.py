"""Web Push subscriptions and the server's VAPID keys."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.crypto import DecryptionFailed, EncryptionUnavailable, secret_box
from app.core.errors import AppError, Conflict, NotFound
from app.models.system import SystemSetting
from app.models.tooling import PushSubscription
from app.push.webpush import VapidKeys, b64u_decode, host_allowed
from app.services.audit import AuditService

VAPID_KEY = "push_vapid"
KINDS = ("approval", "taskDone", "taskFailed")


class PushUnavailable(Conflict):
    code = "push_unavailable"
    message = "Push notifications need APP_ENCRYPTION_KEY on the server."


class InvalidSubscription(AppError):
    status_code = 422
    code = "invalid_subscription"
    message = "This push subscription is not valid."


async def vapid_keys(db: AsyncSession, settings: Settings, user_id: uuid.UUID) -> VapidKeys:
    """The server's VAPID key pair, created on first use, stored encrypted."""
    box = secret_box(settings)
    if not box.available:
        raise PushUnavailable()
    row = (
        await db.execute(
            select(SystemSetting)
            .where(SystemSetting.user_id == user_id, SystemSetting.key == VAPID_KEY)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is not None:
        try:
            return VapidKeys.from_pem(box.decrypt(row.value["private"]))
        except (EncryptionUnavailable, DecryptionFailed, KeyError, ValueError):
            raise PushUnavailable(
                "The push keys cannot be decrypted (APP_ENCRYPTION_KEY changed?)."
            ) from None
    keys = VapidKeys.generate()
    db.add(
        SystemSetting(
            user_id=user_id,
            key=VAPID_KEY,
            value={"private": box.encrypt(keys.pem()), "public": keys.public_b64},
        )
    )
    await db.flush()
    return keys


class PushService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db, self.settings = db, settings

    async def public_key(self, user_id: uuid.UUID) -> str:
        keys = await vapid_keys(self.db, self.settings, user_id)
        await self.db.commit()
        return keys.public_b64

    async def list_subscriptions(self, user_id: uuid.UUID) -> list[PushSubscription]:
        rows = await self.db.execute(
            select(PushSubscription)
            .where(PushSubscription.user_id == user_id)
            .order_by(PushSubscription.created_at)
        )
        return list(rows.scalars())

    async def subscribe(
        self,
        user_id: uuid.UUID,
        *,
        endpoint: str,
        p256dh: str,
        auth: str,
        kinds: list[str],
        locale: str,
        label: str,
    ) -> PushSubscription:
        if not host_allowed(endpoint, self.settings.push_allowed_hosts):
            raise InvalidSubscription("This push service is not allowed (PUSH_ALLOWED_HOSTS).")
        try:
            if len(b64u_decode(p256dh)) != 65 or len(b64u_decode(auth)) != 16:
                raise ValueError
        except ValueError:
            raise InvalidSubscription("The subscription keys are malformed.") from None
        row = (
            await self.db.execute(
                select(PushSubscription).where(PushSubscription.endpoint == endpoint)
            )
        ).scalar_one_or_none()
        if row is not None and row.user_id != user_id:
            raise InvalidSubscription()
        if row is None:
            row = PushSubscription(
                user_id=user_id, endpoint=endpoint, p256dh=p256dh, auth=auth, kinds=[], failures=0
            )
            self.db.add(row)
            await AuditService(self.db).record(
                "push.subscribed",
                "success",
                actor_type="user",
                actor_id=user_id,
                user_id=user_id,
                resource_type="push_subscription",
                details={"label": label[:100]},
            )
        row.p256dh, row.auth = p256dh, auth
        row.kinds = [k for k in dict.fromkeys(kinds) if k in KINDS]
        row.locale = "en" if locale.startswith("en") else "ru"
        row.label = label[:200]
        row.failures = 0
        await self.db.commit()
        return row

    async def unsubscribe(self, user_id: uuid.UUID, endpoint: str) -> None:
        row = (
            await self.db.execute(
                select(PushSubscription).where(
                    PushSubscription.endpoint == endpoint, PushSubscription.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFound("Subscription not found.")
        await self.db.delete(row)
        await AuditService(self.db).record(
            "push.unsubscribed",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="push_subscription",
            details={"label": row.label[:100]},
        )
        await self.db.commit()

    async def mark_sent(self, row: PushSubscription) -> None:
        row.last_sent_at = datetime.now(UTC)
