"""Costs: the usage ledger and the monthly budget.

Every model call adds a `usage_records` row (`record`). The owner sets a monthly limit
in Settings → Costs; crossing the warning share and the limit emits one
`budget.warning` event each per month (in-app + push notifications). With "stop at the
limit" on, new model calls are refused with `budget_exceeded` (`ensure_within_budget`).
Months are calendar months in UTC.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.events import bus
from app.models.system import SystemSetting
from app.models.usage import UsageRecord
from app.providers.base import Usage
from app.providers.gateway import ModelTarget, estimate_cost

BUDGET_KEY = "budget"
ALERTS_KEY = "budget_alerts"


class BudgetExceeded(AppError):
    status_code = 409
    code = "budget_exceeded"
    message = "The monthly budget is used up. Raise the limit in Settings → Costs."


@dataclass(frozen=True)
class Budget:
    monthly_limit_usd: Decimal | None = None
    warn_percent: int = 80
    hard_stop: bool = False


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def month_key(now: datetime | None = None) -> str:
    return month_start(now).strftime("%Y-%m")


async def get_budget(db: AsyncSession, user_id: uuid.UUID) -> Budget:
    row = (
        await db.execute(
            select(SystemSetting).where(
                SystemSetting.user_id == user_id, SystemSetting.key == BUDGET_KEY
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return Budget()
    value = row.value or {}
    limit = value.get("monthly_limit_usd")
    return Budget(
        monthly_limit_usd=Decimal(str(limit)) if limit is not None else None,
        warn_percent=int(value.get("warn_percent", 80)),
        hard_stop=bool(value.get("hard_stop", False)),
    )


async def set_budget(db: AsyncSession, user_id: uuid.UUID, budget: Budget) -> None:
    row = (
        await db.execute(
            select(SystemSetting)
            .where(SystemSetting.user_id == user_id, SystemSetting.key == BUDGET_KEY)
            .with_for_update()
        )
    ).scalar_one_or_none()
    value = {
        "monthly_limit_usd": str(budget.monthly_limit_usd)
        if budget.monthly_limit_usd is not None
        else None,
        "warn_percent": budget.warn_percent,
        "hard_stop": budget.hard_stop,
    }
    if row is None:
        db.add(SystemSetting(user_id=user_id, key=BUDGET_KEY, value=value))
    else:
        row.value = value


async def spent_this_month(db: AsyncSession, user_id: uuid.UUID) -> Decimal:
    total = (
        await db.execute(
            select(func.coalesce(func.sum(UsageRecord.cost_usd), 0)).where(
                UsageRecord.user_id == user_id, UsageRecord.created_at >= month_start()
            )
        )
    ).scalar()
    return Decimal(str(total or 0))


async def ensure_within_budget(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Called before a model call: refuse only when the owner asked to stop at the limit."""
    budget = await get_budget(db, user_id)
    if not budget.hard_stop or budget.monthly_limit_usd is None:
        return
    if await spent_this_month(db, user_id) >= budget.monthly_limit_usd:
        raise BudgetExceeded()


async def record(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    target: ModelTarget,
    usage: Usage,
    source: str,
    agent_id: uuid.UUID | None = None,
    agent_name: str | None = None,
    task_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
) -> None:
    """Add one model call to the ledger (in the caller's transaction) and check the budget."""
    db.add(
        UsageRecord(
            user_id=user_id,
            source=source,
            agent_id=agent_id,
            agent_name=agent_name,
            task_id=task_id,
            run_id=run_id,
            conversation_id=conversation_id,
            model_config_id=target.model_config_id,
            provider_kind=target.provider_kind,
            model=target.model,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cost_usd=estimate_cost(target, usage),
        )
    )
    await db.flush()
    await check_budget(db, user_id)


def thresholds_crossed(
    spent: Decimal, limit: Decimal | None, warn_percent: int, already: list[int]
) -> list[int]:
    """Which alerts are due now (each at most once a month). Pure: tested."""
    if limit is None or limit <= 0:
        return []
    percent = spent / limit * 100
    due = [p for p in (warn_percent, 100) if percent >= p and p not in already]
    return sorted(set(due))


async def check_budget(db: AsyncSession, user_id: uuid.UUID) -> None:
    budget = await get_budget(db, user_id)
    if budget.monthly_limit_usd is None:
        return
    spent = await spent_this_month(db, user_id)
    row = (
        await db.execute(
            select(SystemSetting)
            .where(SystemSetting.user_id == user_id, SystemSetting.key == ALERTS_KEY)
            .with_for_update()
        )
    ).scalar_one_or_none()
    month = month_key()
    sent: list[int] = []
    if row is not None and (row.value or {}).get("month") == month:
        sent = [int(p) for p in row.value.get("sent", [])]
    due = thresholds_crossed(spent, budget.monthly_limit_usd, budget.warn_percent, sent)
    if not due:
        return
    value = {"month": month, "sent": sorted({*sent, *due})}
    if row is None:
        db.add(SystemSetting(user_id=user_id, key=ALERTS_KEY, value=value))
    else:
        row.value = value
    percent = max(due)
    await bus.emit(
        db,
        user_id=user_id,
        type="budget.warning",
        payload={
            "month": month,
            "percent": percent,
            "spent_usd": str(spent.quantize(Decimal("0.01"))),
            "limit_usd": str(budget.monthly_limit_usd),
            "hard_stop": budget.hard_stop,
        },
    )


async def summary(db: AsyncSession, user_id: uuid.UUID, month: str | None = None) -> dict[str, Any]:
    """Totals for one month: overall, per agent, per model, per day."""
    if month:
        start = datetime.strptime(month + "-01", "%Y-%m-%d").replace(tzinfo=UTC)
    else:
        start = month_start()
    end = (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    )
    where = (
        UsageRecord.user_id == user_id,
        UsageRecord.created_at >= start,
        UsageRecord.created_at < end,
    )
    cost = func.coalesce(func.sum(UsageRecord.cost_usd), 0)
    tokens_in = func.coalesce(func.sum(UsageRecord.input_tokens), 0)
    tokens_out = func.coalesce(func.sum(UsageRecord.output_tokens), 0)
    unpriced = func.count().filter(UsageRecord.cost_usd.is_(None))

    total = (
        await db.execute(select(cost, tokens_in, tokens_out, func.count(), unpriced).where(*where))
    ).one()
    # chat answers have no agent: they are grouped as "Chat"
    agent_label = func.coalesce(UsageRecord.agent_name, UsageRecord.source)
    by_agent = (
        await db.execute(
            select(
                UsageRecord.agent_id,
                agent_label,
                UsageRecord.source,
                cost,
                tokens_in,
                tokens_out,
                func.count(),
            )
            .where(*where)
            .group_by(UsageRecord.agent_id, agent_label, UsageRecord.source)
            .order_by(cost.desc(), func.count().desc())
        )
    ).all()
    by_model = (
        await db.execute(
            select(
                UsageRecord.provider_kind,
                UsageRecord.model,
                cost,
                tokens_in,
                tokens_out,
                func.count(),
                unpriced,
            )
            .where(*where)
            .group_by(UsageRecord.provider_kind, UsageRecord.model)
            .order_by(cost.desc(), func.count().desc())
        )
    ).all()
    day = cast(func.timezone("UTC", UsageRecord.created_at), Date)
    by_day = (
        await db.execute(
            select(day, cost, tokens_in + tokens_out).where(*where).group_by(day).order_by(day)
        )
    ).all()
    budget = await get_budget(db, user_id)
    spent = Decimal(str(total[0]))
    limit = budget.monthly_limit_usd
    return {
        "month": start.strftime("%Y-%m"),
        "spent_usd": spent,
        "input_tokens": int(total[1]),
        "output_tokens": int(total[2]),
        "calls": int(total[3]),
        "unpriced_calls": int(total[4]),
        "budget": {
            "monthly_limit_usd": limit,
            "warn_percent": budget.warn_percent,
            "hard_stop": budget.hard_stop,
            "percent": float(spent / limit * 100) if limit else None,
        },
        "by_agent": [
            {
                "agent_id": r[0],
                "name": r[1],
                "source": r[2],
                "cost_usd": Decimal(str(r[3])),
                "input_tokens": int(r[4]),
                "output_tokens": int(r[5]),
                "calls": int(r[6]),
            }
            for r in by_agent
        ],
        "by_model": [
            {
                "provider_kind": r[0],
                "model": r[1],
                "cost_usd": Decimal(str(r[2])),
                "input_tokens": int(r[3]),
                "output_tokens": int(r[4]),
                "calls": int(r[5]),
                "unpriced_calls": int(r[6]),
            }
            for r in by_model
        ],
        "by_day": [
            {"day": r[0], "cost_usd": Decimal(str(r[1])), "tokens": int(r[2])} for r in by_day
        ],
    }
