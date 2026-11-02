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

    async def set_expiry(self, session_id: uuid.UUID, expires_at: datetime) -> None:
        await self.db.execute(
            update(Session).where(Session.id == session_id).values(expires_at=expires_at)
        )

    async def cap_expiry_for_user(
        self, user_id: uuid.UUID, cap: datetime, *, except_session_id: uuid.UUID
    ) -> int:
        """Make the user's other live sessions end no later than ``cap``.

        Only ever shortens: sessions already ending before ``cap`` (expired ones included)
        and revoked ones are left alone. Returns how many sessions were shortened.
        """
        result = await self.db.execute(
            update(Session)
            .where(
                Session.user_id == user_id,
                Session.id != except_session_id,
                Session.revoked_at.is_(None),
                Session.expires_at > cap,
            )
            .values(expires_at=cap)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def revoke_all_for_user(self, user_id: uuid.UUID, at: datetime) -> None:
        await self.db.execute(
            update(Session)
            .where(Session.user_id == user_id, Session.revoked_at.is_(None))
            .values(revoked_at=at)
        )

    async def delete_expired(self, before: datetime) -> int:
        result = await self.db.execute(delete(Session).where(Session.expires_at < before))
        return int(getattr(result, "rowcount", 0) or 0)
