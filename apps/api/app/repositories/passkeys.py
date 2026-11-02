from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.passkey import WebAuthnCredential


class PasskeyRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_for_user(self, user_id: uuid.UUID) -> list[WebAuthnCredential]:
        rows = await self.db.execute(
            select(WebAuthnCredential)
            .where(WebAuthnCredential.user_id == user_id)
            .order_by(WebAuthnCredential.created_at, WebAuthnCredential.id)
        )
        return list(rows.scalars())

    async def count_for_user(self, user_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(WebAuthnCredential)
            .where(WebAuthnCredential.user_id == user_id)
        )
        return int(result.scalar_one())

    async def get_for_user(
        self, user_id: uuid.UUID, passkey_id: uuid.UUID
    ) -> WebAuthnCredential | None:
        result = await self.db.execute(
            select(WebAuthnCredential).where(
                WebAuthnCredential.id == passkey_id, WebAuthnCredential.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def get_by_credential_id(self, credential_id: bytes) -> WebAuthnCredential | None:
        result = await self.db.execute(
            select(WebAuthnCredential).where(WebAuthnCredential.credential_id == credential_id)
        )
        return result.scalar_one_or_none()

    async def add(self, row: WebAuthnCredential) -> WebAuthnCredential:
        self.db.add(row)
        await self.db.flush()
        return row

    async def delete(self, passkey_id: uuid.UUID) -> None:
        await self.db.execute(delete(WebAuthnCredential).where(WebAuthnCredential.id == passkey_id))
