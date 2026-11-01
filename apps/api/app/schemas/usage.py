from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class BudgetOut(BaseModel):
    monthly_limit_usd: Decimal | None
    warn_percent: int
    hard_stop: bool
    percent: float | None


class BudgetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monthly_limit_usd: Decimal | None = Field(default=None, ge=0, le=1_000_000, decimal_places=2)
    warn_percent: int = Field(default=80, ge=10, le=99)
    hard_stop: bool = False


class AgentCost(BaseModel):
    agent_id: uuid.UUID | None
    name: str
    source: str
    cost_usd: Decimal
    input_tokens: int
    output_tokens: int
    calls: int


class ModelCost(BaseModel):
    provider_kind: str | None
    model: str
    cost_usd: Decimal
    input_tokens: int
    output_tokens: int
    calls: int
    unpriced_calls: int


class DayCost(BaseModel):
    day: date
    cost_usd: Decimal
    tokens: int


class CostSummary(BaseModel):
    month: str
    spent_usd: Decimal
    input_tokens: int
    output_tokens: int
    calls: int
    unpriced_calls: int
    budget: BudgetOut
    by_agent: list[AgentCost]
    by_model: list[ModelCost]
    by_day: list[DayCost]
