from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session


class SessionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(self, session: Session) -> Session:
        self.db.add(session)
        await self.db.flush()
        return session

    async def get_by_token_hash(self, token_hash: str) -> Session | None:
        result = await self.db.execute(select(Session).where(Session.token_hash == token_hash))
        return result.scalar_one_or_none()

    async def revoke(self, session_id: uuid.UUID, at: datetime) -> None:
        await self.db.execute(
            update(Session)
            .where(Session.id == session_id, Session.revoked_at.is_(None))
            .values(revoked_at=at)
        )

    async def revoke_all_for_user(self, user_id: uuid.UUID, at: datetime) -> None:
        await self.db.execute(
            update(Session)
            .where(Session.user_id == user_id, Session.revoked_at.is_(None))
            .values(revoked_at=at)
        )

    async def delete_expired(self, before: datetime) -> int:
        result = await self.db.execute(delete(Session).where(Session.expires_at < before))
        return int(getattr(result, "rowcount", 0) or 0)
