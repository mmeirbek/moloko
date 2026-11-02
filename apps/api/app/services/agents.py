"""Agent Manager (spec 14): profiles and run control (run / pause / resume / stop)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.engine import (
    agent_is_busy,
    agent_payload,
    lock_agent,
    lock_task,
    release_agent,
    set_agent_status,
    set_task_status,
)
from app.agents.state import (
    ACTIVE_AGENT,
    AgentStatus,
    AgentType,
    AutonomyLevel,
    InvalidTransition,
    TaskStatus,
    agent_transition_allowed,
)
from app.core.config import Settings
from app.core.errors import AppError, Conflict, NotFound
from app.events import bus
from app.models.agent import Agent, AgentRun
from app.models.provider import ModelConfig
from app.models.task import Task
from app.models.user import User
from app.providers.gateway import ModelUnavailable
from app.schemas.agents import (
    AgentContacts,
    AgentCreate,
    AgentFromTemplate,
    AgentLimits,
    AgentRunRequest,
    AgentUpdate,
    MemorySettings,
)
from app.schemas.tasks import TaskCreate
from app.services.audit import AuditService
from app.services.auth import AGENT_FULL_ACCESS_GRANTED, AuthService, ClientInfo
from app.services.system import ensure_engine_running
from app.services.tasks import AgentBusy, TaskService, after_cancel
from app.tasks.queue import TaskEnqueuer

logger = logging.getLogger("moloko.agents")


class LimitTooHigh(AppError):
    status_code = 422
    code = "limit_too_high"
    message = "A per-agent limit can only be stricter than the global one."


class AgentNotArchived(Conflict):
    code = "agent_not_archived"
    message = "This agent is already in the office."


class AgentNotRestorable(Conflict):
    code = "agent_not_restorable"
    message = "Only your own agents can be brought back; subagents and the Orchestrator cannot."


class InvalidContacts(AppError):
    status_code = 422
    code = "invalid_contacts"
    message = "Contacts can only be your own other agents (not subagents or the Orchestrator)."


class FullAccessNotAllowed(Conflict):
    code = "full_access_not_allowed"
    message = (
        "Only your own persistent agents can get full access (not subagents or the Orchestrator)."
    )


class PasswordRequired(AppError):
    status_code = 422
    code = "password_required"
    message = "Enter your moloko password to confirm."


class AgentNameTaken(Conflict):
    code = "agent_name_taken"
    message = "Another agent in the office already has this name. Choose another name."


def budget_change(old: Decimal | None, agent: Agent) -> dict[str, dict[str, str | None]]:
    """Audit details of a budget change (``{}`` when it did not change)."""
    new = agent.monthly_budget_usd
    if old == new:
        return {}
    return {
        "monthly_budget_usd": {
            "old": str(old) if old is not None else None,
            "new": str(new) if new is not None else None,
        }
    }


class AgentService:
    def __init__(
        self, db: AsyncSession, queue: TaskEnqueuer | None, settings: Settings | None = None
    ) -> None:
        self.db = db
        self.queue = queue
        self.settings = settings
        self.tasks = TaskService(db, queue)
        self.audit = AuditService(db)

    async def get(self, user_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
        agent = await self.db.get(Agent, agent_id)
        if agent is None or agent.user_id != user_id:
            raise NotFound("Agent not found.")
        return agent

    async def list_agents(
        self,
        user_id: uuid.UUID,
        *,
        agent_type: AgentType | None,
        include_archived: bool,
        run_id: uuid.UUID | None,
    ) -> list[Agent]:
        query = select(Agent).where(Agent.user_id == user_id)
        if agent_type is not None:
            query = query.where(Agent.agent_type == agent_type.value)
        if run_id is not None:
            query = query.where(Agent.run_id == run_id)
        if not include_archived:
            query = query.where(Agent.archived_at.is_(None))
        return list((await self.db.execute(query.order_by(Agent.created_at))).scalars())

    async def list_archived(self, user_id: uuid.UUID) -> list[Agent]:
        """Agents removed from the office that can be brought back: the owner's persistent
        agents (subagents and the Orchestrator are never restored), newest removal first."""
        query = (
            select(Agent)
            .where(
                Agent.user_id == user_id,
                Agent.agent_type == AgentType.AUTONOMOUS.value,
                Agent.archived_at.is_not(None),
            )
            .order_by(Agent.archived_at.desc(), Agent.created_at.desc(), Agent.id)
        )
        return list((await self.db.execute(query)).scalars())

    async def _check_model(self, user_id: uuid.UUID, model_config_id: uuid.UUID | None) -> None:
        if model_config_id is None:
            return
        config = await self.db.get(ModelConfig, model_config_id)
        if config is None or config.user_id != user_id:
            raise ModelUnavailable("The selected model does not exist.")

    def _check_limits(self, limits: AgentLimits | None, memory: MemorySettings | None) -> None:
        """Per-agent limits may only be stricter than the global ones (spec 7.2, 14.2)."""
        if self.settings is None:
            return
        caps = {
            "max_steps": (limits.max_steps if limits else None, self.settings.max_steps_per_run),
            "run_timeout_seconds": (
                limits.run_timeout_seconds if limits else None,
                self.settings.run_timeout_seconds,
            ),
            "max_context_chars": (
                memory.max_context_chars if memory else None,
                self.settings.memory_context_max_chars,
            ),
        }
        for name, (value, cap) in caps.items():
            if value is not None and value > cap:
                raise LimitTooHigh(
                    f"{name} can be at most {cap} (the global limit).",
                    details={"field": name, "max": cap},
                )

    async def _check_tools(self, user_id: uuid.UUID, names: list[str]) -> None:
        if self.settings is not None and names:
            from app.services.tools import ToolsService

            await ToolsService(self.db, self.settings).validate_names(user_id, names)

    async def _check_workspace(self, user_id: uuid.UUID, workspace_id: uuid.UUID | None) -> None:
        if workspace_id is None:
            return
        from app.models.tooling import Workspace

        ws = await self.db.get(Workspace, workspace_id)
        if ws is None or ws.user_id != user_id or ws.kind != "project":
            raise NotFound("Project workspace not found.")

    async def _contacts(
        self, user_id: uuid.UUID, contacts: AgentContacts, self_id: uuid.UUID | None
    ) -> dict[str, object]:
        """Stored compactly: {} = everyone. A list may only name the owner's persistent
        agents (deleted ones may stay in it; they cannot be contacted anyway)."""
        if contacts.mode == "all":
            return {}
        if contacts.mode == "none":
            return {"mode": "none"}
        ids = list(dict.fromkeys(contacts.agent_ids))
        if self_id is not None and self_id in ids:
            raise InvalidContacts("An agent is always allowed to talk to itself; remove it.")
        found = set(
            (
                await self.db.execute(
                    select(Agent.id).where(
                        Agent.id.in_(ids),
                        Agent.user_id == user_id,
                        Agent.agent_type == AgentType.AUTONOMOUS.value,
                    )
                )
            ).scalars()
        )
        unknown = [str(i) for i in ids if i not in found]
        if unknown:
            raise InvalidContacts(details={"agent_ids": unknown})
        return {"mode": "list", "agent_ids": [str(i) for i in ids]}

    async def _free_name(self, user_id: uuid.UUID, base: str) -> str:
        """``base``, or ``base 2``, ``base 3``… when an agent in the office has that name."""
        taken = set(
            (
                await self.db.execute(
                    select(Agent.name).where(Agent.user_id == user_id, Agent.archived_at.is_(None))
                )
            ).scalars()
        )
        name, n = base, 2
        while name in taken:
            name, n = f"{base[: 100 - len(str(n)) - 1]} {n}", n + 1
        return name[:100]

    async def create_from_template(self, user_id: uuid.UUID, data: AgentFromTemplate) -> Agent:
        """One click in the office: a persistent agent from a ready-made template or from
        one of the owner's own templates. It stays idle until it is given a task."""
        from app.agents.templates import BY_KEY, localized

        template = BY_KEY.get(data.template)
        if template is None:
            return await self._create_from_own_template(user_id, data)
        name = await self._free_name(
            user_id, (data.name or localized(template.names, data.locale)).strip()
        )
        return await self.create(
            user_id,
            AgentCreate(
                name=name,
                description=localized(template.descriptions, data.locale),
                agent_type=AgentType.AUTONOMOUS,
                specialization=template.specialization,
                system_prompt=template.system_prompt,
                autonomy_level=AutonomyLevel.SUPERVISED,
                allowed_tools=list(template.allowed_tools),
            ),
            origin={"template": template.key, "template_source": "builtin"},
        )

    async def _create_from_own_template(self, user_id: uuid.UUID, data: AgentFromTemplate) -> Agent:
        """An agent with an own template's configuration. What changed since it was saved
        is smoothed over instead of refusing the drop: tools that no longer exist are
        left out and limits above today's global ones are lowered to them."""
        from app.services.agent_templates import AgentTemplateService, parse_own_key

        template_id = parse_own_key(data.template)
        if template_id is None or self.settings is None:
            raise NotFound("Unknown agent template.")
        row = await AgentTemplateService(self.db, self.settings).get_own(user_id, template_id)
        from app.services.tools import ToolsService

        known = await ToolsService(self.db, self.settings).known_names(user_id)
        tools = [t for t in dict.fromkeys(row.allowed_tools or []) if t in known]
        overrides = {
            name: rule
            for name, rule in ((row.permissions or {}).get("tools") or {}).items()
            if name in tools and rule in ("approve", "deny")
        }
        limits = AgentLimits(**(row.limits or {}))
        memory = MemorySettings(**(row.memory_settings or {}))
        caps = (
            ("max_steps", self.settings.max_steps_per_run),
            ("run_timeout_seconds", self.settings.run_timeout_seconds),
        )
        for field, cap in caps:
            value = getattr(limits, field)
            if value is not None and value > cap:
                setattr(limits, field, cap)
        if (
            memory.max_context_chars is not None
            and memory.max_context_chars > self.settings.memory_context_max_chars
        ):
            memory.max_context_chars = self.settings.memory_context_max_chars
        name = await self._free_name(user_id, (data.name or row.name).strip())
        return await self.create(
            user_id,
            AgentCreate(
                name=name,
                description=row.description,
                agent_type=AgentType.AUTONOMOUS,
                specialization=row.specialization,
                model_config_id=row.model_config_id,
                system_prompt=row.system_prompt,
                autonomy_level=AutonomyLevel(row.autonomy_level),
                allowed_tools=tools,
                limits=limits,
                memory_settings=memory,
                tool_overrides=overrides,
                monthly_budget_usd=row.monthly_budget_usd,
            ),
            origin={"template": str(row.id), "template_source": "own"},
        )

    async def create(
        self, user_id: uuid.UUID, data: AgentCreate, *, origin: dict[str, str] | None = None
    ) -> Agent:
        if data.agent_type == AgentType.SUBAGENT:
            raise InvalidTransition("Subagents are created by the Orchestrator, not by hand.")
        self._check_limits(data.limits, data.memory_settings)
        await self._check_model(user_id, data.model_config_id)
        await self._check_tools(user_id, [*data.allowed_tools, *data.tool_overrides])
        await self._check_workspace(user_id, data.workspace_id)
        contacts = await self._contacts(user_id, data.contacts, None)
        agent = Agent(
            user_id=user_id,
            name=data.name,
            description=data.description,
            agent_type=data.agent_type.value,
            specialization=data.specialization,
            model_config_id=data.model_config_id,
            system_prompt=data.system_prompt,
            autonomy_level=data.autonomy_level.value,
            allowed_tools=list(dict.fromkeys(data.allowed_tools)),
            permissions={"tools": dict(data.tool_overrides)} if data.tool_overrides else {},
            workspace_id=data.workspace_id,
            status=AgentStatus.IDLE.value,
            limits=data.limits.model_dump(exclude_none=True),
            memory_settings=data.memory_settings.model_dump(exclude_defaults=True),
            monthly_budget_usd=data.monthly_budget_usd,
            contacts=contacts,
        )
        self.db.add(agent)
        await self.db.flush()
        await self.db.refresh(agent)
        await bus.emit(
            self.db,
            user_id=user_id,
            type="agent.created",
            agent_id=agent.id,
            payload={"agent": agent_payload(agent)},
        )
        await self.audit.record(
            "agent.created",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="agent",
            resource_id=str(agent.id),
            details={
                "name": agent.name,
                "type": agent.agent_type,
                "autonomy": agent.autonomy_level,
                **(
                    {"monthly_budget_usd": str(agent.monthly_budget_usd)}
                    if agent.monthly_budget_usd is not None
                    else {}
                ),
                **(origin or {}),
            },
        )
        await bus.commit(self.db)
        return agent

    async def update(self, user_id: uuid.UUID, agent_id: uuid.UUID, data: AgentUpdate) -> Agent:
        agent = await lock_agent(self.db, agent_id)
        if agent.user_id != user_id or agent.archived_at is not None:
            raise NotFound("Agent not found.")
        self._check_limits(data.limits, data.memory_settings)
        changed: list[str] = []
        fields = data.model_fields_set
        for name in ("name", "description", "system_prompt"):
            value = getattr(data, name)
            if value is not None and value != getattr(agent, name):
                setattr(agent, name, value)
                changed.append(name)
        if "specialization" in fields and data.specialization != agent.specialization:
            agent.specialization = data.specialization
            changed.append("specialization")
        if "model_config_id" in fields and data.model_config_id != agent.model_config_id:
            await self._check_model(user_id, data.model_config_id)
            agent.model_config_id = data.model_config_id
            changed.append("model_config_id")
        if data.autonomy_level is not None and data.autonomy_level.value != agent.autonomy_level:
            agent.autonomy_level = data.autonomy_level.value
            changed.append("autonomy_level")
        if data.allowed_tools is not None:
            tools = list(dict.fromkeys(data.allowed_tools))
            await self._check_tools(user_id, tools)
            if tools != agent.allowed_tools:
                agent.allowed_tools = tools
                changed.append("allowed_tools")
        if data.tool_overrides is not None:
            await self._check_tools(user_id, list(data.tool_overrides))
            permissions = {**(agent.permissions or {}), "tools": dict(data.tool_overrides)}
            if permissions != agent.permissions:
                agent.permissions = permissions
                changed.append("tool_overrides")
        if "workspace_id" in fields and data.workspace_id != agent.workspace_id:
            await self._check_workspace(user_id, data.workspace_id)
            agent.workspace_id = data.workspace_id
            changed.append("workspace_id")
        if data.limits is not None:
            limits = data.limits.model_dump(exclude_none=True)
            if limits != agent.limits:
                agent.limits = limits
                changed.append("limits")
        if data.memory_settings is not None:
            memory_settings = data.memory_settings.model_dump(exclude_defaults=True)
            if memory_settings != agent.memory_settings:
                agent.memory_settings = memory_settings
                changed.append("memory_settings")
        if data.contacts is not None:
            contacts = await self._contacts(user_id, data.contacts, agent.id)
            if contacts != (agent.contacts or {}):
                agent.contacts = contacts
                changed.append("contacts")
        old_budget = agent.monthly_budget_usd
        if "monthly_budget_usd" in fields and data.monthly_budget_usd != old_budget:
            if agent.agent_type == AgentType.SUBAGENT.value and data.monthly_budget_usd:
                raise InvalidTransition(
                    "A subagent counts against the budget of the agent above it."
                )
            agent.monthly_budget_usd = data.monthly_budget_usd
            changed.append("monthly_budget_usd")
        if changed:
            agent.config_version += 1
            agent.updated_at = datetime.now(UTC)
            await bus.emit(
                self.db,
                user_id=user_id,
                type="agent.updated",
                agent_id=agent.id,
                payload={"changed": changed, "agent": agent_payload(agent)},
            )
            await self.audit.record(
                "agent.updated",
                "success",
                actor_type="user",
                actor_id=user_id,
                user_id=user_id,
                resource_type="agent",
                resource_id=str(agent.id),
                details={"changed": changed, **budget_change(old_budget, agent)},
            )
            if "monthly_budget_usd" in changed and self.settings is not None:
                from app.services.usage import check_agent_budget

                # a lower limit may already be crossed: warn now, not at the next call
                await check_agent_budget(
                    self.db, user_id, agent.id, self.settings.agent_budget_warn_percent
                )
        await bus.commit(self.db)
        return agent

    # --- «Полный доступ» (owner's decision, see docs/decisions.md) ------------------------

    async def remove_standing_approval(
        self, user_id: uuid.UUID, agent_id: uuid.UUID, rule_id: str
    ) -> Agent:
        """The owner takes back a «больше не спрашивать»: this kind of action asks again."""
        from app.tools import standing

        agent = await lock_agent(self.db, agent_id)
        if agent.user_id != user_id:
            raise NotFound("Agent not found.")
        gone = standing.remove(agent, rule_id)
        if gone is None:
            raise NotFound("This permission is not there any more.")
        self._touch(agent)
        await bus.emit(
            self.db,
            user_id=user_id,
            type="agent.updated",
            agent_id=agent.id,
            payload={"changed": ["standing_approvals"], "agent": agent_payload(agent)},
        )
        await self.audit.record(
            "agent.standing_approval_removed",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="agent",
            resource_id=str(agent.id),
            details={"tool": gone.get("tool"), "scope": gone.get("scope", "")},
        )
        await bus.commit(self.db)
        return agent

    async def set_full_access(
        self,
        user: User,
        agent_id: uuid.UUID,
        *,
        enabled: bool,
        password: str | None,
        client: ClientInfo,
    ) -> Agent:
        """Turn full access on (confirmed with the owner's password; wrong ones count toward
        the shared login lockout) or off (no password). Only persistent agents can have it;
        it has no expiry. Switching to the current state changes nothing."""
        agent = await lock_agent(self.db, agent_id)
        if agent.user_id != user.id or agent.archived_at is not None:
            raise NotFound("Agent not found.")
        if agent.agent_type != AgentType.AUTONOMOUS.value:
            raise FullAccessNotAllowed()
        if not enabled:
            await self._revoke_full_access(agent, user.id, "owner", client.ip_address)
            await bus.commit(self.db)
            return agent
        if not password:
            raise PasswordRequired(details={"field": "password"})
        assert self.settings is not None
        subject_key = await AuthService(self.db, self.settings).confirm_password(
            user, password, client, purpose="agent_full_access"
        )
        if agent.full_access_since is not None:
            return agent
        agent.full_access_since = datetime.now(UTC)
        self._touch(agent)
        await bus.emit(
            self.db,
            user_id=user.id,
            type="agent.updated",
            agent_id=agent.id,
            payload={"changed": ["full_access"], "agent": agent_payload(agent)},
        )
        await self.audit.record(
            AGENT_FULL_ACCESS_GRANTED,
            "success",
            actor_type="user",
            actor_id=user.id,
            user_id=user.id,
            resource_type="agent",
            resource_id=str(agent.id),
            ip_address=client.ip_address,
            # subject_key: a correct password restarts the lockout count (app.services.auth)
            details={
                "subject_key": subject_key,
                "name": agent.name,
                "autonomy": agent.autonomy_level,
            },
        )
        await bus.commit(self.db)
        logger.info("agent_full_access_granted", extra={"agent_id": str(agent.id)})
        return agent

    async def _revoke_full_access(
        self, agent: Agent, user_id: uuid.UUID, reason: str, ip_address: str | None = None
    ) -> None:
        if agent.full_access_since is None:
            return
        since = agent.full_access_since
        agent.full_access_since = None
        self._touch(agent)
        await bus.emit(
            self.db,
            user_id=user_id,
            type="agent.updated",
            agent_id=agent.id,
            payload={"changed": ["full_access"], "agent": agent_payload(agent)},
        )
        await self.audit.record(
            "agent.full_access_revoked",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="agent",
            resource_id=str(agent.id),
            ip_address=ip_address,
            details={"name": agent.name, "since": since.isoformat(), "reason": reason},
        )
        logger.info(
            "agent_full_access_revoked", extra={"agent_id": str(agent.id), "reason": reason}
        )

    @staticmethod
    def _touch(agent: Agent) -> None:
        agent.config_version += 1
        agent.updated_at = datetime.now(UTC)

    async def archive(self, user_id: uuid.UUID, agent_id: uuid.UUID) -> None:
        """DELETE keeps history: the profile is archived, its runs and tasks stay."""
        agent = await lock_agent(self.db, agent_id)
        if agent.user_id != user_id or agent.archived_at is not None:
            raise NotFound("Agent not found.")
        if agent_is_busy(agent):
            raise AgentBusy("Stop the agent before deleting it.")
        # A removed agent loses full access; brought back, it needs the password again.
        await self._revoke_full_access(agent, user_id, "archived")
        agent.archived_at = datetime.now(UTC)
        await bus.emit(
            self.db,
            user_id=user_id,
            type="agent.updated",
            agent_id=agent.id,
            payload={"changed": ["archived_at"], "agent": agent_payload(agent)},
        )
        await self.audit.record(
            "agent.deleted",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="agent",
            resource_id=str(agent.id),
        )
        await bus.commit(self.db)
        await after_cancel(self.db, self.queue, user_id)  # its waiting questions are withdrawn

    async def restore(
        self, user_id: uuid.UUID, agent_id: uuid.UUID, name: str | None = None
    ) -> Agent:
        """Bring an archived persistent agent back into the office: idle, no task, with its
        settings, memory and history as they were. ``name`` renames it on the way back
        (for when another agent in the office took its name meanwhile)."""
        agent = await lock_agent(self.db, agent_id)
        if agent.user_id != user_id:
            raise NotFound("Agent not found.")
        if agent.agent_type != AgentType.AUTONOMOUS.value:
            raise AgentNotRestorable()
        if agent.archived_at is None:
            raise AgentNotArchived()
        new_name = name.strip() if name and name.strip() else agent.name
        clash = (
            await self.db.execute(
                select(Agent.id)
                .where(
                    Agent.user_id == user_id,
                    Agent.id != agent.id,
                    Agent.archived_at.is_(None),
                    Agent.agent_type != AgentType.SUBAGENT.value,
                    Agent.name == new_name,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if clash is not None:
            raise AgentNameTaken(
                details={"field": "name", "name": new_name, "agent_id": str(clash)}
            )

        changed = ["archived_at"]
        old_name = agent.name
        agent.archived_at = None
        if new_name != old_name:
            agent.name = new_name
            agent.config_version += 1
            changed.append("name")
        agent.updated_at = datetime.now(UTC)
        # Back as idle with no task (an archived agent was never busy: archive refuses that).
        await release_agent(self.db, agent, to=AgentStatus.IDLE, reason="restored")
        await bus.emit(
            self.db,
            user_id=user_id,
            type="agent.updated",
            agent_id=agent.id,
            payload={"changed": changed, "agent": agent_payload(agent)},
        )
        details: dict[str, str] = {"name": agent.name}
        if "name" in changed:
            details["renamed_from"] = old_name
        await self.audit.record(
            "agent.restored",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="agent",
            resource_id=str(agent.id),
            details=details,
        )
        await bus.commit(self.db)
        return agent

    # --- run control ---------------------------------------------------------------------

    async def run(
        self, user_id: uuid.UUID, agent_id: uuid.UUID, req: AgentRunRequest
    ) -> tuple[Task, AgentRun]:
        await ensure_engine_running(self.db, user_id)
        agent = await self.get(user_id, agent_id)
        if agent.agent_type == AgentType.SUBAGENT.value:
            raise InvalidTransition("Subagents are run by their Orchestrator.")
        if req.task_id is not None:
            task = await self.tasks.get(user_id, req.task_id)
            if task.agent_id not in (None, agent.id):
                raise InvalidTransition("This task is assigned to another agent.")
            if task.agent_id is None:
                task.agent_id = agent.id
                await bus.commit(self.db)
        else:
            if not req.title:
                raise InvalidTransition("Give the task a title.")
            task = await self.tasks.create(
                user_id,
                TaskCreate(
                    title=req.title, description=req.description, agent_id=agent.id, start=False
                ),
            )
        return await self.tasks.start(user_id, task.id)

    async def _current_task(self, agent: Agent) -> Task | None:
        return await lock_task(self.db, agent.current_task_id) if agent.current_task_id else None

    async def pause(self, user_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
        agent = await lock_agent(self.db, agent_id)
        if agent.user_id != user_id:
            raise NotFound("Agent not found.")
        if AgentStatus(agent.status) not in ACTIVE_AGENT:
            raise InvalidTransition("Only a working agent can be paused.")
        await set_agent_status(self.db, agent, AgentStatus.PAUSED, reason="paused_by_user")
        task = await self._current_task(agent)
        if task is not None and TaskStatus(task.status) in (TaskStatus.RUNNING, TaskStatus.QUEUED):
            run = await self.db.get(AgentRun, task.run_id) if task.run_id else None
            if TaskStatus(task.status) == TaskStatus.RUNNING:
                await set_task_status(self.db, task, TaskStatus.WAITING, reason="paused", run=run)
        await self.audit.record(
            "agent.paused",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="agent",
            resource_id=str(agent.id),
        )
        await bus.commit(self.db)
        return agent

    async def resume(self, user_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
        await ensure_engine_running(self.db, user_id)
        agent = await lock_agent(self.db, agent_id)
        if agent.user_id != user_id:
            raise NotFound("Agent not found.")
        task = await self._current_task(agent)
        if AgentStatus(agent.status) == AgentStatus.PAUSED:
            await set_agent_status(
                self.db,
                agent,
                AgentStatus(agent.paused_from or AgentStatus.WORKING),
                reason="resumed_by_user",
            )
        elif not (task is not None and TaskStatus(task.status) == TaskStatus.WAITING):
            raise InvalidTransition("This agent is not paused or waiting.")
        requeue = False
        if task is not None and TaskStatus(task.status) == TaskStatus.WAITING:
            run = await self.db.get(AgentRun, task.run_id) if task.run_id else None
            await set_task_status(self.db, task, TaskStatus.QUEUED, reason="resumed", run=run)
            requeue = True
        await self.audit.record(
            "agent.resumed",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="agent",
            resource_id=str(agent.id),
        )
        await bus.commit(self.db)
        if requeue and task is not None and self.queue is not None:
            await self.queue.enqueue_task(task.id)
        return agent

    async def stop(self, user_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
        agent = await lock_agent(self.db, agent_id)
        if agent.user_id != user_id:
            raise NotFound("Agent not found.")
        task = await self._current_task(agent)
        if task is not None and TaskStatus(task.status) not in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        ):
            await self.tasks._cancel_tree(task, "agent_stopped")
        elif agent_transition_allowed(
            AgentStatus(agent.status),
            AgentStatus.IDLE,
            agent_type=AgentType(agent.agent_type),
            paused_from=AgentStatus(agent.paused_from) if agent.paused_from else None,
        ):
            await release_agent(self.db, agent, to=AgentStatus.IDLE, reason="agent_stopped")
        await self.audit.record(
            "agent.stopped",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="agent",
            resource_id=str(agent.id),
        )
        await bus.commit(self.db)
        await after_cancel(self.db, self.queue, user_id)
        await self.db.refresh(agent)
        return agent
