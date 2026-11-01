"""``Idempotency-Key`` support for endpoints that start work (spec 12).

Same key + same body → the stored response is returned and no new work starts.
Same key + different body → 422. A concurrent duplicate → 409 until the first finishes.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, Conflict
from app.models.system import IdempotencyKey


class IdempotencyKeyReused(AppError):
    status_code = 422
    code = "idempotency_key_reused"
    message = "This Idempotency-Key was already used for a different request."


class RequestInProgress(Conflict):
    code = "request_in_progress"
    message = "The same request is still being processed."


def _hash(body: Any) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


async def idempotent[T: BaseModel](
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    scope: str,
    key: str | None,
    body: Any,
    model: type[T],
    action: Callable[[], Awaitable[T]],
) -> T:
    if not key:
        return await action()
    key = key[:128]
    request_hash = _hash(body)
    existing = (
        await db.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.user_id == user_id,
                IdempotencyKey.scope == scope,
                IdempotencyKey.key == key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise IdempotencyKeyReused()
        if existing.response_body is None:
            raise RequestInProgress()
        return model.model_validate(existing.response_body)

    marker = IdempotencyKey(user_id=user_id, scope=scope, key=key, request_hash=request_hash)
    db.add(marker)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise RequestInProgress() from None
    try:
        result = await action()
    except Exception:
        await db.rollback()
        await db.delete(await db.merge(marker))
        await db.commit()
        raise
    marker = await db.merge(marker)
    marker.response_status = 200
    marker.response_body = result.model_dump(mode="json")
    await db.commit()
    return result
