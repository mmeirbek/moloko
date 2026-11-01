"""Tool Registry (spec 15.1): built-in tools from code + MCP tools from the database,
merged with the owner's switches (``tools`` rows)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.agent import Agent
from app.models.tooling import McpServer, Tool
from app.providers.base import ToolSpec
from app.tools.base import BaseTool
from app.tools.builtin.browser import BROWSER_TOOLS
from app.tools.builtin.files import FILE_TOOLS
from app.tools.builtin.github import GITHUB_TOOLS
from app.tools.builtin.memory import MEMORY_TOOLS
from app.tools.builtin.search import SEARCH_TOOLS
from app.tools.builtin.terminal import TERMINAL_TOOLS
from app.tools.builtin.web import WEB_TOOLS
from app.tools.mcp import McpTool
from app.tools.policy import CatalogEntry

BUILTIN: dict[str, BaseTool] = {
    t.name: t
    for t in (
        *FILE_TOOLS,
        *TERMINAL_TOOLS,
        *WEB_TOOLS,
        *BROWSER_TOOLS,
        *GITHUB_TOOLS,
        *MEMORY_TOOLS,
        *SEARCH_TOOLS,
    )
}


async def catalog(
    db: AsyncSession, user_id: uuid.UUID, settings: Settings
) -> dict[str, CatalogEntry]:
    rows = {
        r.name: r for r in (await db.execute(select(Tool).where(Tool.user_id == user_id))).scalars()
    }
    entries: dict[str, CatalogEntry] = {}
    cache: dict[Any, bool] = {}  # one availability check per kind (e.g. GitHub connected)
    for name, tool in BUILTIN.items():
        check = type(tool).available
        if check not in cache:
            cache[check] = await tool.available(db, user_id, settings)
        row = rows.get(name)
        entries[name] = CatalogEntry(
            tool=tool, enabled=row.enabled if row else True, available=cache[check]
        )
    servers = {
        s.id: s
        for s in (await db.execute(select(McpServer).where(McpServer.user_id == user_id))).scalars()
    }
    for row in rows.values():
        if row.source != "mcp" or row.server_id not in servers:
            continue
        server = servers[row.server_id]
        entries[row.name] = CatalogEntry(
            tool=McpTool(row, server),
            enabled=row.enabled,
            available=row.available and server.enabled,
        )
    return entries


def specs_for(agent: Agent, entries: dict[str, CatalogEntry]) -> tuple[ToolSpec, ...]:
    """What the model is told it can call: allowed, enabled and available tools only.
    (Every call is still authorized again before it runs.)"""
    specs = []
    for name in agent.allowed_tools or []:
        entry = entries.get(name)
        if entry is not None and entry.enabled and entry.available:
            specs.append(
                ToolSpec(
                    name=name,
                    description=entry.tool.description,
                    input_schema=entry.tool.input_schema,
                )
            )
    return tuple(specs)
