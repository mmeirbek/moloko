from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.repositories.audit_logs import AuditLogRepository

ActorType = Literal["user", "agent", "system", "anonymous"]
Outcome = Literal["success", "failure", "denied"]


class AuditService:
    """Writes to the append-only audit journal inside the caller's transaction.

    ``details`` must never contain secrets (passwords, tokens, API keys).
    """

    def __init__(self, db: AsyncSession) -> None:
        self.repo = AuditLogRepository(db)

    async def record(
        self,
        action: str,
        outcome: Outcome,
        *,
        actor_type: ActorType,
        actor_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        ip_address: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> AuditLog:
        return await self.repo.add(
            AuditLog(
                action=action,
                outcome=outcome,
                actor_type=actor_type,
                actor_id=actor_id,
                user_id=user_id,
                resource_type=resource_type,
                resource_id=resource_id,
                ip_address=ip_address,
                details=details or {},
            )
        )
