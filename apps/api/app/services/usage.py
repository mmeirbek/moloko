"""Costs: the usage ledger, the monthly budget and the per-agent budgets.

Every model call adds a `usage_records` row (`record`). The owner sets a monthly limit
in Settings → Costs; crossing the warning share and the limit emits one
`budget.warning` event each per month (in-app + push notifications). With "stop at the
limit" on, new model calls are refused with `budget_exceeded` (`ensure_within_budget`).

An agent may also have its own monthly limit (`agents.monthly_budget_usd`). Its
subagents' calls count against it (`budget_agent_id`: the nearest persistent agent or
Orchestrator above a subagent). At `AGENT_BUDGET_WARN_PERCENT` and at 100 % the owner
gets a `budget.warning` event with `scope: "agent"`; at the limit the agent's new model
calls are always refused with `agent_budget_exceeded` (`ensure_within_agent_budget`).
Months are calendar months in UTC.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, case, cast, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.events import bus
from app.models.agent import Agent
from app.models.system import SystemSetting
from app.models.usage import UsageRecord
from app.providers.base import Usage
from app.providers.gateway import ModelTarget, estimate_cost

BUDGET_KEY = "budget"
ALERTS_KEY = "budget_alerts"
AGENT_ALERTS_PREFIX = "agent_budget_alerts:"  # + the agent's id: alerts sent this month
MAX_PARENT_HOPS = 10  # subagents nest at most MAX_SUBAGENT_DEPTH (≤ 5) deep


class BudgetExceeded(AppError):
    status_code = 409
    code = "budget_exceeded"
    message = "The monthly budget is used up. Raise the limit in Settings → Costs."


class AgentBudgetExceeded(AppError):
    status_code = 409
    code = "agent_budget_exceeded"
    message = "This agent's monthly budget is used up. Raise it on the agent's page."


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


# --- per-agent budgets ----------------------------------------------------------------


@dataclass(frozen=True)
class AgentBudgetStatus:
    agent_id: uuid.UUID  # the budget holder (the agent, or the one above a subagent)
    name: str
    limit: Decimal | None
    spent: Decimal

    @property
    def percent(self) -> float | None:
        return float(self.spent / self.limit * 100) if self.limit else None

    @property
    def exceeded(self) -> bool:
        return self.limit is not None and self.spent >= self.limit


async def budget_holder_id(db: AsyncSession, agent_id: uuid.UUID) -> uuid.UUID:
    """Whose budget an agent's model calls count against: the agent itself, or for a
    subagent the nearest persistent agent / Orchestrator above it."""
    current = agent_id
    for _ in range(MAX_PARENT_HOPS):
        row = (
            await db.execute(
                select(Agent.agent_type, Agent.parent_agent_id).where(Agent.id == current)
            )
        ).one_or_none()
        if row is None or row[0] != "subagent" or row[1] is None:
            return current
        current = row[1]
    return current


async def agent_spent_this_month(db: AsyncSession, holder_id: uuid.UUID) -> Decimal:
    total = (
        await db.execute(
            select(func.coalesce(func.sum(UsageRecord.cost_usd), 0)).where(
                UsageRecord.budget_agent_id == holder_id, UsageRecord.created_at >= month_start()
            )
        )
    ).scalar()
    return Decimal(str(total or 0))


async def agent_budget_status(db: AsyncSession, agent_id: uuid.UUID) -> AgentBudgetStatus:
    holder_id = await budget_holder_id(db, agent_id)
    row = (
        await db.execute(select(Agent.name, Agent.monthly_budget_usd).where(Agent.id == holder_id))
    ).one_or_none()
    name, limit = (row[0], row[1]) if row is not None else ("", None)
    return AgentBudgetStatus(
        agent_id=holder_id,
        name=name,
        limit=Decimal(str(limit)) if limit is not None else None,
        spent=await agent_spent_this_month(db, holder_id),
    )


async def ensure_within_agent_budget(db: AsyncSession, agent_id: uuid.UUID) -> None:
    """Called before an agent's model call: refuse it once the agent (or, for a subagent,
    the agent above it) has used its own monthly budget. Always a hard stop."""
    status = await agent_budget_status(db, agent_id)
    if status.exceeded:
        assert status.limit is not None
        spent = status.spent.quantize(Decimal("0.01"))
        raise AgentBudgetExceeded(
            f"The monthly budget of «{status.name}» (${status.limit}) is used up: "
            f"${spent} spent. Raise it on the agent's page.",
            details={
                "agent_id": str(status.agent_id),
                "limit_usd": str(status.limit),
                "spent_usd": str(spent),
            },
        )


async def check_agent_budget(
    db: AsyncSession, user_id: uuid.UUID, holder_id: uuid.UUID, warn_percent: int
) -> None:
    """Warn the owner (one `budget.warning` per threshold, month and limit) when an
    agent's spending crosses ``warn_percent`` or 100 % of its own limit. A changed limit
    starts the alerts afresh."""
    row = (
        await db.execute(select(Agent.name, Agent.monthly_budget_usd).where(Agent.id == holder_id))
    ).one_or_none()
    if row is None or row[1] is None:
        return
    name, limit = row[0], Decimal(str(row[1]))
    spent = await agent_spent_this_month(db, holder_id)
    key = f"{AGENT_ALERTS_PREFIX}{holder_id}"
    # Parallel subagents may record at the same moment: create the row race-free, then lock it.
    await db.execute(
        pg_insert(SystemSetting)
        .values(id=uuid.uuid4(), user_id=user_id, key=key, value={})
        .on_conflict_do_nothing(index_elements=["user_id", "key"])
    )
    alerts = (
        await db.execute(
            select(SystemSetting)
            .where(SystemSetting.user_id == user_id, SystemSetting.key == key)
            .with_for_update()
        )
    ).scalar_one()
    month, limit_text = month_key(), str(limit)
    value = alerts.value or {}
    sent: list[int] = []
    if value.get("month") == month and value.get("limit_usd") == limit_text:
        sent = [int(p) for p in value.get("sent", [])]
    due = thresholds_crossed(spent, limit, warn_percent, sent)
    if not due:
        return
    alerts.value = {"month": month, "limit_usd": limit_text, "sent": sorted({*sent, *due})}
    await bus.emit(
        db,
        user_id=user_id,
        type="budget.warning",
        agent_id=holder_id,
        payload={
            "scope": "agent",
            "agent_id": str(holder_id),
            "agent_name": name,
            "month": month,
            "percent": max(due),
            "spent_usd": str(spent.quantize(Decimal("0.01"))),
            "limit_usd": limit_text,
            "hard_stop": True,
        },
    )


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
    agent_warn_percent: int | None = None,
) -> None:
    """Add one model call to the ledger (in the caller's transaction) and check the
    budgets: the global one, and the agent's own (``agent_warn_percent`` = its warning
    threshold, from the settings)."""
    holder_id = await budget_holder_id(db, agent_id) if agent_id is not None else None
    db.add(
        UsageRecord(
            user_id=user_id,
            source=source,
            agent_id=agent_id,
            agent_name=agent_name,
            budget_agent_id=holder_id,
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
    if holder_id is not None and agent_warn_percent is not None:
        await check_agent_budget(db, user_id, holder_id, agent_warn_percent)


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
    # One row per budget holder (an agent together with its subagents' calls); chat
    # answers have no agent: they are grouped by source ("Chat").
    holder = func.coalesce(UsageRecord.budget_agent_id, UsageRecord.agent_id)
    no_holder_source = case((holder.is_(None), UsageRecord.source), else_=None)
    by_agent = (
        await db.execute(
            select(
                holder,
                no_holder_source,
                func.max(UsageRecord.agent_name).filter(UsageRecord.agent_id == holder),
                func.max(UsageRecord.agent_name),
                func.max(UsageRecord.source),
                cost,
                tokens_in,
                tokens_out,
                func.count(),
                func.coalesce(
                    func.sum(UsageRecord.cost_usd).filter(UsageRecord.agent_id != holder), 0
                ),
            )
            .where(*where)
            .group_by(holder, no_holder_source)
            .order_by(cost.desc(), func.count().desc())
        )
    ).all()
    holder_ids = [r[0] for r in by_agent if r[0] is not None]
    agents = {
        a.id: a
        for a in (
            await db.execute(
                select(Agent).where(Agent.user_id == user_id, Agent.id.in_(holder_ids))
            )
        ).scalars()
    }
    this_month = start == month_start()
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
        "by_agent": [_agent_row(r, agents.get(r[0]), this_month) for r in by_agent],
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


def _agent_row(r: Any, agent: Agent | None, this_month: bool) -> dict[str, Any]:
    """One `by_agent` row of `summary`: the budget holder's current name and limit."""
    cost = Decimal(str(r[5]))
    limit = agent.monthly_budget_usd if agent is not None else None
    if agent is not None:
        source = "orchestrator" if agent.agent_type == "orchestrator" else "agent"
    else:
        source = r[1] or r[4]
    return {
        "agent_id": r[0],
        "name": agent.name if agent is not None else (r[2] or r[3] or source),
        "source": source,
        "cost_usd": cost,
        "input_tokens": int(r[6]),
        "output_tokens": int(r[7]),
        "calls": int(r[8]),
        "subagents_cost_usd": Decimal(str(r[9])),
        "monthly_budget_usd": limit,
        "percent": float(cost / limit * 100) if limit and this_month else None,
    }
