"""Agent templates: the built-in ones (``app/agents/templates.py``) and the owner's own
("Save as template" on an agent's page).

An own template keeps an agent's reusable configuration — name, description,
specialization, instructions, model, autonomy, tools and per-tool rules, limits, memory
settings and monthly budget. It does not keep the agent's memory entries, task history or
project workspace: a new agent from it starts with an empty memory and its own folders.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentType
from app.agents.templates import TEMPLATES, localized
from app.core.config import Settings
from app.core.errors import Conflict, NotFound
from app.events import bus
from app.models.agent import Agent, SavedAgentTemplate
from app.schemas.agents import AgentTemplateOut
from app.services.audit import AuditService


class TemplateNameTaken(Conflict):
    code = "template_name_taken"
    message = "You already have a template with this name. Choose another name."


class TemplateLimitReached(Conflict):
    code = "template_limit_reached"
    message = "You have the maximum number of own templates. Delete one first."


class AgentNotTemplatable(Conflict):
    code = "agent_not_templatable"
    message = "Only your own persistent agents can be saved as a template."


def builtin_out(locale: str) -> list[AgentTemplateOut]:
    return [
        AgentTemplateOut(
            key=t.key,
            source="builtin",
            id=None,
            name=localized(t.names, locale),
            description=localized(t.descriptions, locale),
            specialization=t.specialization,
            allowed_tools=list(t.allowed_tools),
            autonomy_level="supervised",
            model_config_id=None,
            monthly_budget_usd=None,
            created_at=None,
        )
        for t in TEMPLATES
    ]


def own_out(row: SavedAgentTemplate) -> AgentTemplateOut:
    return AgentTemplateOut(
        key=str(row.id),
        source="own",
        id=row.id,
        name=row.name,
        description=row.description,
        specialization=row.specialization or "",
        allowed_tools=list(row.allowed_tools or []),
        autonomy_level=row.autonomy_level,
        model_config_id=row.model_config_id,
        monthly_budget_usd=row.monthly_budget_usd,
        created_at=row.created_at,
    )


def parse_own_key(key: str) -> uuid.UUID | None:
    """An own template's key is its id; built-in keys are never UUIDs."""
    try:
        return uuid.UUID(key)
    except ValueError:
        return None


class AgentTemplateService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.audit = AuditService(db)

    async def list(self, user_id: uuid.UUID, locale: str) -> list[AgentTemplateOut]:
        """Built-in templates first, then the owner's own (newest first)."""
        own = (
            await self.db.execute(
                select(SavedAgentTemplate)
                .where(SavedAgentTemplate.user_id == user_id)
                .order_by(SavedAgentTemplate.created_at.desc(), SavedAgentTemplate.id)
            )
        ).scalars()
        return [*builtin_out(locale), *(own_out(r) for r in own)]

    async def get_own(self, user_id: uuid.UUID, template_id: uuid.UUID) -> SavedAgentTemplate:
        row = await self.db.get(SavedAgentTemplate, template_id)
        if row is None or row.user_id != user_id:
            raise NotFound("Template not found.")
        return row

    async def save_from_agent(
        self, user_id: uuid.UUID, agent_id: uuid.UUID, name: str | None
    ) -> SavedAgentTemplate:
        agent = await self.db.get(Agent, agent_id)
        if agent is None or agent.user_id != user_id or agent.archived_at is not None:
            raise NotFound("Agent not found.")
        if agent.agent_type != AgentType.AUTONOMOUS.value:
            raise AgentNotTemplatable()
        template_name = (name or "").strip() or agent.name
        await self._check_name(user_id, template_name)
        count = (
            await self.db.execute(
                select(func.count())
                .select_from(SavedAgentTemplate)
                .where(SavedAgentTemplate.user_id == user_id)
            )
        ).scalar_one()
        if count >= self.settings.agent_templates_max:
            raise TemplateLimitReached(details={"max": self.settings.agent_templates_max})
        row = SavedAgentTemplate(
            user_id=user_id,
            name=template_name,
            description=agent.description,
            specialization=agent.specialization,
            model_config_id=agent.model_config_id,
            system_prompt=agent.system_prompt,
            autonomy_level=agent.autonomy_level,
            allowed_tools=list(agent.allowed_tools or []),
            permissions=dict(agent.permissions or {}),
            limits=dict(agent.limits or {}),
            memory_settings=dict(agent.memory_settings or {}),
            monthly_budget_usd=agent.monthly_budget_usd,
            source_agent_id=agent.id,
        )
        self.db.add(row)
        try:
            await self.db.flush()
        except IntegrityError:  # the same name saved at the same moment
            await self.db.rollback()
            raise TemplateNameTaken(details={"field": "name", "name": template_name}) from None
        await self.db.refresh(row)
        await self.audit.record(
            "agent_template.saved",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="agent_template",
            resource_id=str(row.id),
            details={"name": row.name, "agent_id": str(agent.id)},
        )
        await bus.commit(self.db)
        return row

    async def delete(self, user_id: uuid.UUID, template_id: uuid.UUID) -> None:
        row = await self.get_own(user_id, template_id)
        details: dict[str, Any] = {"name": row.name}
        await self.db.delete(row)
        await self.audit.record(
            "agent_template.deleted",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="agent_template",
            resource_id=str(template_id),
            details=details,
        )
        await bus.commit(self.db)

    async def _check_name(self, user_id: uuid.UUID, name: str) -> None:
        clash = (
            await self.db.execute(
                select(SavedAgentTemplate.id).where(
                    SavedAgentTemplate.user_id == user_id, SavedAgentTemplate.name == name
                )
            )
        ).scalar_one_or_none()
        if clash is not None:
            raise TemplateNameTaken(
                details={"field": "name", "name": name, "template_id": str(clash)}
            )
