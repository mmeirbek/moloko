from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Header, Query, Response, status

from app.agents.state import AgentType
from app.api.deps import Client, CurrentAuth, DbSession, QueueDep, SettingsDep
from app.schemas.agents import (
    AgentBudgetOut,
    AgentCreate,
    AgentFromTemplate,
    AgentFullAccessUpdate,
    AgentMessageItem,
    AgentOut,
    AgentRestore,
    AgentRunRequest,
    AgentTemplateOut,
    AgentUpdate,
    FullAccessForAllOut,
    SaveAsTemplate,
    StartedRun,
)
from app.schemas.common import Page
from app.schemas.memories import MemoryContextOut
from app.schemas.tasks import RunOut, TaskOut
from app.services.agent_templates import AgentTemplateService, own_out
from app.services.agents import AgentService
from app.services.correspondence import list_for_agent
from app.services.idempotency import idempotent
from app.services.memories import MemoryService
from app.services.usage import agent_budget_status, month_key

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=list[AgentOut])
async def list_agents(
    ctx: CurrentAuth,
    db: DbSession,
    queue: QueueDep,
    agent_type: AgentType | None = None,
    run_id: uuid.UUID | None = None,
    include_archived: bool = Query(False),
) -> list[AgentOut]:
    rows = await AgentService(db, queue).list_agents(
        ctx.user.id, agent_type=agent_type, include_archived=include_archived, run_id=run_id
    )
    return [AgentOut.model_validate(a) for a in rows]


@router.get(
    "/archived",
    response_model=list[AgentOut],
    summary="Agents removed from the office that can be brought back (newest first)",
)
async def list_archived_agents(ctx: CurrentAuth, db: DbSession, queue: QueueDep) -> list[AgentOut]:
    rows = await AgentService(db, queue).list_archived(ctx.user.id)
    return [AgentOut.model_validate(a) for a in rows]


@router.get(
    "/full-access",
    response_model=FullAccessForAllOut,
    summary="Whether «Полный доступ всем агентам» is on",
)
async def get_full_access_for_all(ctx: CurrentAuth) -> FullAccessForAllOut:
    since = ctx.user.full_access_all_since
    return FullAccessForAllOut(enabled=since is not None, since=since)


@router.put(
    "/full-access",
    response_model=FullAccessForAllOut,
    summary="Turn «Полный доступ» on (confirmed with the password) or off for every agent",
)
async def set_full_access_for_all(
    body: AgentFullAccessUpdate,
    ctx: CurrentAuth,
    db: DbSession,
    queue: QueueDep,
    settings: SettingsDep,
    client: Client,
) -> FullAccessForAllOut:
    since = await AgentService(db, queue, settings).set_full_access_for_all(
        ctx.user, enabled=body.enabled, password=body.password, client=client
    )
    return FullAccessForAllOut(enabled=since is not None, since=since)


@router.get(
    "/templates",
    response_model=list[AgentTemplateOut],
    summary="Ready-made agents: the built-in templates, then the owner's own (newest first)",
)
async def list_templates(
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    locale: str = Query("ru", max_length=8),
) -> list[AgentTemplateOut]:
    return await AgentTemplateService(db, settings).list(ctx.user.id, locale)


@router.delete(
    "/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one of the owner's own templates (agents made from it stay)",
)
async def delete_template(
    template_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, settings: SettingsDep
) -> Response:
    await AgentTemplateService(db, settings).delete(ctx.user.id, template_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/from-template",
    response_model=AgentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a persistent agent from a template (built-in or own; it waits for a task)",
)
async def create_from_template(
    body: AgentFromTemplate, ctx: CurrentAuth, db: DbSession, queue: QueueDep, settings: SettingsDep
) -> AgentOut:
    agent = await AgentService(db, queue, settings).create_from_template(ctx.user.id, body)
    return AgentOut.model_validate(agent)


@router.post("", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
async def create_agent(
    body: AgentCreate, ctx: CurrentAuth, db: DbSession, queue: QueueDep, settings: SettingsDep
) -> AgentOut:
    agent = await AgentService(db, queue, settings).create(ctx.user.id, body)
    return AgentOut.model_validate(agent)


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, queue: QueueDep
) -> AgentOut:
    return AgentOut.model_validate(await AgentService(db, queue).get(ctx.user.id, agent_id))


@router.patch("/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: uuid.UUID,
    body: AgentUpdate,
    ctx: CurrentAuth,
    db: DbSession,
    queue: QueueDep,
    settings: SettingsDep,
) -> AgentOut:
    agent = await AgentService(db, queue, settings).update(ctx.user.id, agent_id, body)
    return AgentOut.model_validate(agent)


@router.put(
    "/{agent_id}/full-access",
    response_model=AgentOut,
    summary="Turn «Полный доступ» on (confirmed with the password) or off for a persistent agent",
)
async def set_full_access(
    agent_id: uuid.UUID,
    body: AgentFullAccessUpdate,
    ctx: CurrentAuth,
    db: DbSession,
    queue: QueueDep,
    settings: SettingsDep,
    client: Client,
) -> AgentOut:
    agent = await AgentService(db, queue, settings).set_full_access(
        ctx.user, agent_id, enabled=body.enabled, password=body.password, client=client
    )
    return AgentOut.model_validate(agent)


@router.delete(
    "/{agent_id}/standing-approvals/{rule_id}",
    response_model=AgentOut,
    summary="Take back a «больше не спрашивать»: this kind of action needs approval again",
)
async def remove_standing_approval(
    agent_id: uuid.UUID, rule_id: str, ctx: CurrentAuth, db: DbSession, queue: QueueDep
) -> AgentOut:
    agent = await AgentService(db, queue).remove_standing_approval(ctx.user.id, agent_id, rule_id)
    return AgentOut.model_validate(agent)


@router.post(
    "/{agent_id}/save-template",
    response_model=AgentTemplateOut,
    status_code=status.HTTP_201_CREATED,
    summary="Save the agent's configuration as an own template (no memory or history)",
)
async def save_as_template(
    agent_id: uuid.UUID,
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    body: SaveAsTemplate | None = None,
) -> AgentTemplateOut:
    row = await AgentTemplateService(db, settings).save_from_agent(
        ctx.user.id, agent_id, body.name if body is not None else None
    )
    return own_out(row)


@router.get(
    "/{agent_id}/budget",
    response_model=AgentBudgetOut,
    summary="This month's spending against the agent's own budget (subagents: the one above)",
)
async def agent_budget(
    agent_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, queue: QueueDep, settings: SettingsDep
) -> AgentBudgetOut:
    await AgentService(db, queue).get(ctx.user.id, agent_id)
    budget = await agent_budget_status(db, agent_id)
    return AgentBudgetOut(
        agent_id=agent_id,
        budget_agent_id=budget.agent_id,
        budget_agent_name=budget.name,
        month=month_key(),
        spent_usd=budget.spent,
        monthly_budget_usd=budget.limit,
        warn_percent=settings.agent_budget_warn_percent,
        percent=budget.percent,
        exceeded=budget.exceeded,
    )


@router.get(
    "/{agent_id}/messages",
    response_model=Page[AgentMessageItem],
    summary="Correspondence with other agents: questions, answers, notes (newest first)",
)
async def agent_messages(
    agent_id: uuid.UUID,
    ctx: CurrentAuth,
    db: DbSession,
    queue: QueueDep,
    direction: Literal["all", "in", "out"] = "all",
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
) -> Page[AgentMessageItem]:
    await AgentService(db, queue).get(ctx.user.id, agent_id)
    items, next_cursor = await list_for_agent(
        db, ctx.user.id, agent_id, direction=direction, limit=limit, cursor=cursor
    )
    return Page(items=items, next_cursor=next_cursor)


@router.get(
    "/{agent_id}/memory-context",
    response_model=MemoryContextOut,
    summary="Exactly what this agent's prompt receives from memory",
)
async def agent_memory_context(
    agent_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, settings: SettingsDep
) -> MemoryContextOut:
    mc = await MemoryService(db, settings).context_for(ctx.user.id, agent_id)
    return MemoryContextOut(
        enabled=mc.enabled,
        text=mc.text,
        included=mc.included,
        omitted=mc.omitted,
        chars=mc.chars,
        max_chars=mc.max_chars,
    )


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Archive the agent (history is kept)",
)
async def delete_agent(
    agent_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, queue: QueueDep
) -> Response:
    await AgentService(db, queue).archive(ctx.user.id, agent_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{agent_id}/restore",
    response_model=AgentOut,
    summary="Bring an archived agent back into the office (idle, no task)",
)
async def restore_agent(
    agent_id: uuid.UUID,
    ctx: CurrentAuth,
    db: DbSession,
    queue: QueueDep,
    body: AgentRestore | None = None,
) -> AgentOut:
    agent = await AgentService(db, queue).restore(
        ctx.user.id, agent_id, body.name if body is not None else None
    )
    return AgentOut.model_validate(agent)


@router.post(
    "/{agent_id}/run", response_model=StartedRun, summary="Give the agent a task and start it"
)
async def run_agent(
    agent_id: uuid.UUID,
    body: AgentRunRequest,
    ctx: CurrentAuth,
    db: DbSession,
    queue: QueueDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> StartedRun:
    async def action() -> StartedRun:
        task, run = await AgentService(db, queue).run(ctx.user.id, agent_id, body)
        return StartedRun(
            task=TaskOut.model_validate(task),
            run=RunOut.model_validate(run) if run is not None else None,
        )

    return await idempotent(
        db,
        user_id=ctx.user.id,
        scope=f"POST /agents/{agent_id}/run",
        key=idempotency_key,
        body=body.model_dump(mode="json"),
        model=StartedRun,
        action=action,
    )


@router.post("/{agent_id}/pause", response_model=AgentOut)
async def pause_agent(
    agent_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, queue: QueueDep
) -> AgentOut:
    return AgentOut.model_validate(await AgentService(db, queue).pause(ctx.user.id, agent_id))


@router.post("/{agent_id}/resume", response_model=AgentOut)
async def resume_agent(
    agent_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, queue: QueueDep
) -> AgentOut:
    return AgentOut.model_validate(await AgentService(db, queue).resume(ctx.user.id, agent_id))


@router.post("/{agent_id}/stop", response_model=AgentOut)
async def stop_agent(
    agent_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, queue: QueueDep
) -> AgentOut:
    return AgentOut.model_validate(await AgentService(db, queue).stop(ctx.user.id, agent_id))
