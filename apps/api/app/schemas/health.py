from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

CheckStatus = Literal["ok", "error"]


class HealthChecks(BaseModel):
    database: CheckStatus
    redis: CheckStatus


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    checks: HealthChecks


class LivenessResponse(BaseModel):
    status: Literal["ok"]
