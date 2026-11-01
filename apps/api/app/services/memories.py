"""Memory records (spec 17): CRUD, change history, scope rules and access control."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentType, MemoryType
from app.core.config import Settings
from app.core.errors import AppError, NotFound
from app.events import bus
from app.memory.context import MemoryContext, build_memory_context
from app.models.agent import Agent
from app.models.memory import Memory, MemoryRevision
from app.schemas.memories import MemoryCreate, MemoryUpdate
from app.services.audit import AuditService

AGENT_SCOPED = {MemoryType.AGENT, MemoryType.TASK_CONTEXT, MemoryType.CONVERSATION_CONTEXT}


class InvalidMemory(AppError):
    status_code = 422
    code = "invalid_memory"
    message = "This memory entry is not valid."


class MemoryService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.audit = AuditService(db)

    async def _agent(self, user_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
        agent = await self.db.get(Agent, agent_id)
        if agent is None or agent.user_id != user_id or agent.archived_at is not None:
            raise NotFound("Agent not found.")
        return agent

    async def get(self, user_id: uuid.UUID, memory_id: uuid.UUID) -> Memory:
        memory = await self.db.get(Memory, memory_id)
        if memory is None or memory.user_id != user_id:
            raise NotFound("Memory not found.")
        return memory

    async def list_memories(
        self,
        user_id: uuid.UUID,
        *,
        agent_id: uuid.UUID | None,
        shared: bool | None,
        memory_type: MemoryType | None,
        project: str | None,
        q: str | None,
        limit: int,
    ) -> list[Memory]:
        query = select(Memory).where(Memory.user_id == user_id)
        if agent_id is not None:
            query = query.where(Memory.agent_id == agent_id)
        if shared is True:
            query = query.where(Memory.agent_id.is_(None))
        elif shared is False:
            query = query.where(Memory.agent_id.is_not(None))
        if memory_type is not None:
            query = query.where(Memory.memory_type == memory_type.value)
        if project:
            query = query.where(Memory.project == project)
        if q:
            pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            query = query.where(or_(Memory.title.ilike(pattern), Memory.content.ilike(pattern)))
        query = query.order_by(Memory.pinned.desc(), Memory.updated_at.desc()).limit(limit)
        return list((await self.db.execute(query)).scalars())

    def _check_content(self, content: str) -> str:
        content = content.strip()
        if not content:
            raise InvalidMemory("The memory text is empty.")
        limit = self.settings.memory_entry_max_chars
        if len(content) > limit:
            raise InvalidMemory(
                f"The memory text is too long (at most {limit} characters).",
                code="memory_too_long",
                details={"max_chars": limit, "chars": len(content)},
            )
        return content

    async def _check_scope(
        self,
        user_id: uuid.UUID,
        memory_type: MemoryType,
        agent_id: uuid.UUID | None,
        project: str | None,
    ) -> None:
        if memory_type == MemoryType.USER and agent_id is not None:
            raise InvalidMemory(
                "Memories about you are shared by all agents: leave the agent empty."
            )
        if memory_type in AGENT_SCOPED and agent_id is None:
            raise InvalidMemory("Choose the agent this memory belongs to.")
        if memory_type == MemoryType.PROJECT and not project:
            raise InvalidMemory("Give the project a name.")
        if agent_id is not None:
            agent = await self._agent(user_id, agent_id)
            if agent.agent_type == AgentType.SUBAGENT.value:
                raise InvalidMemory("Subagents are temporary and have no memory of their own.")

    def _revision(self, memory: Memory, changed_by: str) -> MemoryRevision:
        return MemoryRevision(
            memory_id=memory.id,
            user_id=memory.user_id,
            revision=memory.revision,
            memory_type=memory.memory_type,
            agent_id=memory.agent_id,
            project=memory.project,
            title=memory.title,
            content=memory.content,
            pinned=memory.pinned,
            changed_by=changed_by,
        )

    async def _audit(
        self, action: str, user_id: uuid.UUID, memory: Memory, **details: object
    ) -> None:
        # Never the content: memory can hold personal details.
        await self.audit.record(
            action,
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="memory",
            resource_id=str(memory.id),
            details={
                "type": memory.memory_type,
                "agent_id": str(memory.agent_id) if memory.agent_id else None,
                **details,
            },
        )

    async def create(self, user_id: uuid.UUID, data: MemoryCreate) -> Memory:
        project = data.project.strip() if data.project else None
        await self._check_scope(user_id, data.memory_type, data.agent_id, project)
        memory = Memory(
            user_id=user_id,
            agent_id=data.agent_id,
            memory_type=data.memory_type.value,
            project=project,
            title=data.title.strip() or data.title,
            content=self._check_content(data.content),
            pinned=data.pinned,
            revision=1,
            created_by="user",
        )
        self.db.add(memory)
        await self.db.flush()
        self.db.add(self._revision(memory, "user"))
        await self._audit("memory.created", user_id, memory)
        await bus.commit(self.db)
        return memory

    async def update(self, user_id: uuid.UUID, memory_id: uuid.UUID, data: MemoryUpdate) -> Memory:
        memory = (
            await self.db.execute(select(Memory).where(Memory.id == memory_id).with_for_update())
        ).scalar_one_or_none()
        if memory is None or memory.user_id != user_id:
            raise NotFound("Memory not found.")
        changed: list[str] = []
        if data.title is not None and data.title.strip() != memory.title:
            memory.title = data.title.strip()
            changed.append("title")
        if data.content is not None:
            content = self._check_content(data.content)
            if content != memory.content:
                memory.content = content
                changed.append("content")
        if "project" in data.model_fields_set:
            project = data.project.strip() if data.project else None
            if project != memory.project:
                await self._check_scope(
                    user_id, MemoryType(memory.memory_type), memory.agent_id, project
                )
                memory.project = project
                changed.append("project")
        if data.pinned is not None and data.pinned != memory.pinned:
            memory.pinned = data.pinned
            changed.append("pinned")
        if changed:
            memory.revision += 1
            memory.updated_at = datetime.now(UTC)
            self.db.add(self._revision(memory, "user"))
            await self._audit("memory.updated", user_id, memory, changed=changed)
        await bus.commit(self.db)
        return memory

    async def delete(self, user_id: uuid.UUID, memory_id: uuid.UUID) -> None:
        """Deleting removes the entry and its history (the owner asked to forget it)."""
        memory = await self.get(user_id, memory_id)
        await self._audit("memory.deleted", user_id, memory)
        await self.db.delete(memory)
        await bus.commit(self.db)

    async def revisions(self, user_id: uuid.UUID, memory_id: uuid.UUID) -> list[MemoryRevision]:
        await self.get(user_id, memory_id)
        rows = await self.db.execute(
            select(MemoryRevision)
            .where(MemoryRevision.memory_id == memory_id)
            .order_by(MemoryRevision.revision.desc())
        )
        return list(rows.scalars())

    async def context_for(self, user_id: uuid.UUID, agent_id: uuid.UUID) -> MemoryContext:
        agent = await self._agent(user_id, agent_id)
        return await build_memory_context(self.db, agent, self.settings)
