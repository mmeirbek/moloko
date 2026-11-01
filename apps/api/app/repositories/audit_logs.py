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

    async def page(
        self,
        *,
        user_id: object,
        action_prefix: str | None,
        outcome: str | None,
        before: tuple[datetime, object] | None,
        limit: int,
    ) -> list[AuditLog]:
        """Newest first. Anonymous entries (failed logins) belong to the owner's view too."""
        from sqlalchemy import or_, tuple_

        query = select(AuditLog).where(or_(AuditLog.user_id == user_id, AuditLog.user_id.is_(None)))
        if action_prefix:
            escaped = action_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.where(AuditLog.action.like(escaped + "%"))
        if outcome:
            query = query.where(AuditLog.outcome == outcome)
        if before is not None:
            query = query.where(tuple_(AuditLog.created_at, AuditLog.id) < tuple_(*before))
        rows = await self.db.execute(
            query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit)
        )
        return list(rows.scalars())
