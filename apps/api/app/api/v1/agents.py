from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, Query, Response, status

from app.agents.state import AgentType
from app.agents.templates import TEMPLATES, localized
from app.api.deps import CurrentAuth, DbSession, QueueDep, SettingsDep
from app.schemas.agents import (
    AgentCreate,
    AgentFromTemplate,
    AgentOut,
    AgentRunRequest,
    AgentTemplateOut,
    AgentUpdate,
    StartedRun,
)
from app.schemas.memories import MemoryContextOut
from app.schemas.tasks import RunOut, TaskOut
from app.services.agents import AgentService
from app.services.idempotency import idempotent
from app.services.memories import MemoryService

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


@router.get("/templates", response_model=list[AgentTemplateOut], summary="Ready-made agents")
async def list_templates(
    ctx: CurrentAuth, locale: str = Query("ru", max_length=8)
) -> list[AgentTemplateOut]:
    return [
        AgentTemplateOut(
            key=t.key,
            name=localized(t.names, locale),
            description=localized(t.descriptions, locale),
            specialization=t.specialization,
            allowed_tools=list(t.allowed_tools),
        )
        for t in TEMPLATES
    ]


@router.post(
    "/from-template",
    response_model=AgentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a persistent agent from a template (it waits for a task)",
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
        return StartedRun(task=TaskOut.model_validate(task), run=RunOut.model_validate(run))

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
