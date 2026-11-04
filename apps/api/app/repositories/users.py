from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def full_access_for_all(self, user_id: uuid.UUID) -> bool:
        """Whether «Полный доступ всем агентам» is on: every persistent agent added to the
        office now gets full access as it is added."""
        since = await self.db.execute(select(User.full_access_all_since).where(User.id == user_id))
        return since.scalar_one_or_none() is not None

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self.db.get(User, user_id)

    async def get_by_username(self, username: str) -> User | None:
        result = await self.db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def count(self) -> int:
        result = await self.db.execute(select(func.count()).select_from(User))
        return int(result.scalar_one())

    async def add(self, user: User) -> User:
        self.db.add(user)
        await self.db.flush()
        return user

    async def set_session_ttl_hours(self, user_id: uuid.UUID, hours: int | None) -> None:
        await self.db.execute(
            update(User).where(User.id == user_id).values(session_ttl_hours=hours)
        )
