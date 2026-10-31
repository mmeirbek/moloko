from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


class AuditLogRepository:
    """Insert and read only — audit rows are never updated or deleted."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(self, entry: AuditLog) -> AuditLog:
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def count_since(self, *, action: str, subject_key: str, since: datetime) -> int:
        """Count ``action`` entries for ``details.subject_key`` newer than ``since``."""
        result = await self.db.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == action,
                AuditLog.created_at > since,
                AuditLog.details["subject_key"].astext == subject_key,
            )
        )
        return int(result.scalar_one())

    async def last_time(self, *, action: str, subject_key: str) -> datetime | None:
        result = await self.db.execute(
            select(func.max(AuditLog.created_at)).where(
                AuditLog.action == action,
                AuditLog.details["subject_key"].astext == subject_key,
            )
        )
        return result.scalar_one_or_none()
