"""Tool Registry management for the owner: list tools, turn them on/off, classify MCP tools."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, NotFound
from app.events import bus
from app.models.tooling import McpServer, Tool
from app.schemas.tooling import ToolOut, ToolUpdate
from app.services.audit import AuditService
from app.tools.mcp import McpTool
from app.tools.policy import CatalogEntry
from app.tools.registry import BUILTIN, catalog


class UnknownTool(AppError):
    status_code = 422
    code = "unknown_tool"
    message = "There is no such tool."


def tool_out(name: str, entry: CatalogEntry, server: McpServer | None = None) -> ToolOut:
    tool = entry.tool
    return ToolOut(
        name=name,
        title=tool.title,
        description=tool.description,
        group=tool.group,
        category=tool.category.value,
        source="mcp" if isinstance(tool, McpTool) else "builtin",
        server_id=server.id if server else None,
        server_name=server.name if server else None,
        enabled=entry.enabled,
        available=entry.available,
        input_schema=tool.input_schema,
    )


class ToolsService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db, self.settings = db, settings

    async def list_tools(self, user_id: uuid.UUID) -> list[ToolOut]:
        entries = await catalog(self.db, user_id, self.settings)
        out = []
        for name, entry in entries.items():
            server = entry.tool.server if isinstance(entry.tool, McpTool) else None
            out.append(tool_out(name, entry, server))
        return out

    async def validate_names(self, user_id: uuid.UUID, names: list[str]) -> None:
        known = set(BUILTIN) | set(
            (
                await self.db.execute(
                    select(Tool.name).where(Tool.user_id == user_id, Tool.source == "mcp")
                )
            ).scalars()
        )
        unknown = list(dict.fromkeys(n for n in names if n not in known))
        if unknown:
            raise UnknownTool(
                f"Unknown tools: {', '.join(unknown[:5])}.", details={"tools": unknown[:20]}
            )

    async def update(self, user_id: uuid.UUID, name: str, data: ToolUpdate) -> ToolOut:
        row = (
            await self.db.execute(
                select(Tool).where(Tool.user_id == user_id, Tool.name == name).with_for_update()
            )
        ).scalar_one_or_none()
        builtin = BUILTIN.get(name)
        if row is None and builtin is None:
            raise NotFound("Tool not found.")
        if row is None:
            assert builtin is not None
            row = Tool(
                user_id=user_id,
                name=name,
                source="builtin",
                description="",
                category=None,
                input_schema={},
                enabled=True,
                available=True,
            )
            self.db.add(row)
        changed: dict[str, object] = {}
        if data.enabled is not None and data.enabled != row.enabled:
            row.enabled = data.enabled
            changed["enabled"] = data.enabled
        if data.category is not None:
            if row.source != "mcp":
                raise AppError(
                    "Built-in tools have a fixed category.", code="category_fixed", status_code=422
                )
            if data.category.value != row.category:
                row.category = data.category.value
                changed["category"] = data.category.value
        if changed:
            await AuditService(self.db).record(
                "tool.updated",
                "success",
                actor_type="user",
                actor_id=user_id,
                user_id=user_id,
                resource_type="tool",
                resource_id=name,
                details=changed,
            )
        await bus.commit(self.db)
        entries = await catalog(self.db, user_id, self.settings)
        entry = entries[name]
        server = entry.tool.server if isinstance(entry.tool, McpTool) else None
        return tool_out(name, entry, server)
