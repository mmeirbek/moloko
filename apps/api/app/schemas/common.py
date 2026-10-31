from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime

from pydantic import BaseModel

from app.core.errors import AppError


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


class InvalidCursor(AppError):
    status_code = 422
    code = "invalid_cursor"
    message = "The pagination cursor is invalid."


def encode_cursor(at: datetime, item_id: uuid.UUID) -> str:
    raw = json.dumps([at.isoformat(), str(item_id)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        at, item_id = json.loads(base64.urlsafe_b64decode(padded))
        return datetime.fromisoformat(at), uuid.UUID(item_id)
    except (ValueError, TypeError) as exc:
        raise InvalidCursor() from exc
