from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ErrorBody(BaseModel):
    id: str
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    """Shape of every error response (spec section 12)."""

    error: ErrorBody
