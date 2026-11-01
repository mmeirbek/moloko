from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import CurrentAuth, DbSession
from app.schemas.usage import BudgetIn, BudgetOut, CostSummary
from app.services.audit import AuditService
from app.services.usage import Budget, check_budget, get_budget, set_budget, summary

router = APIRouter(prefix="/costs", tags=["costs"])


@router.get("", response_model=CostSummary, summary="Tokens and approximate cost for a month")
async def costs(
    ctx: CurrentAuth, db: DbSession, month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$")
) -> CostSummary:
    return CostSummary.model_validate(await summary(db, ctx.user.id, month))


@router.put("/budget", response_model=BudgetOut, summary="Monthly limit and warnings")
async def update_budget(body: BudgetIn, ctx: CurrentAuth, db: DbSession) -> BudgetOut:
    await set_budget(
        db,
        ctx.user.id,
        Budget(
            monthly_limit_usd=body.monthly_limit_usd,
            warn_percent=body.warn_percent,
            hard_stop=body.hard_stop,
        ),
    )
    await AuditService(db).record(
        "costs.budget_updated",
        "success",
        actor_type="user",
        actor_id=ctx.user.id,
        user_id=ctx.user.id,
        resource_type="budget",
        details={
            "monthly_limit_usd": str(body.monthly_limit_usd) if body.monthly_limit_usd else None,
            "warn_percent": body.warn_percent,
            "hard_stop": body.hard_stop,
        },
    )
    await check_budget(db, ctx.user.id)  # a lower limit may already be crossed
    from app.events import bus

    await bus.commit(db)
    budget = await get_budget(db, ctx.user.id)
    data = await summary(db, ctx.user.id)
    return BudgetOut(
        monthly_limit_usd=budget.monthly_limit_usd,
        warn_percent=budget.warn_percent,
        hard_stop=budget.hard_stop,
        percent=data["budget"]["percent"],
    )
