"""MCP servers (spec 15.5): add, configure, refresh tools, remove. Tools start disabled."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.crypto import secret_box
from app.core.errors import NotFound
from app.events import bus
from app.models.tooling import McpServer, Tool
from app.schemas.tooling import McpServerCreate, McpServerOut, McpServerUpdate
from app.services.audit import AuditService
from app.services.tools import tool_out
from app.tools.mcp import McpTool, refresh_server, slugify
from app.tools.policy import CatalogEntry


async def server_out(db: AsyncSession, server: McpServer) -> McpServerOut:
    rows = (
        await db.execute(select(Tool).where(Tool.server_id == server.id).order_by(Tool.name))
    ).scalars()
    tools = [
        tool_out(
            r.name,
            CatalogEntry(McpTool(r, server), r.enabled, r.available and server.enabled),
            server,
        )
        for r in rows
    ]
    return McpServerOut(
        id=server.id,
        name=server.name,
        slug=server.slug,
        url=server.url,
        has_token=bool(server.secret_encrypted),
        enabled=server.enabled,
        status=server.status,
        last_error=server.last_error,
        last_checked_at=server.last_checked_at,
        server_info=server.server_info or {},
        tools=tools,
    )


class McpService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db, self.settings = db, settings

    async def _get(self, user_id: uuid.UUID, server_id: uuid.UUID) -> McpServer:
        server = await self.db.get(McpServer, server_id)
        if server is None or server.user_id != user_id:
            raise NotFound("MCP server not found.")
        return server

    async def list_servers(self, user_id: uuid.UUID) -> list[McpServerOut]:
        rows = (
            await self.db.execute(
                select(McpServer).where(McpServer.user_id == user_id).order_by(McpServer.created_at)
            )
        ).scalars()
        return [await server_out(self.db, s) for s in rows]

    async def _unique_slug(self, user_id: uuid.UUID, name: str) -> str:
        base = slugify(name)
        taken = set(
            (
                await self.db.execute(select(McpServer.slug).where(McpServer.user_id == user_id))
            ).scalars()
        )
        slug, n = base, 2
        while slug in taken:
            slug, n = f"{base[:14]}{n}", n + 1
        return slug

    async def create(self, user_id: uuid.UUID, data: McpServerCreate) -> McpServerOut:
        server = McpServer(
            user_id=user_id,
            name=data.name.strip(),
            slug=await self._unique_slug(user_id, data.name),
            url=data.url.strip(),
            enabled=True,
            status="unknown",
            server_info={},
            secret_encrypted=secret_box(self.settings).encrypt(data.token.get_secret_value())
            if data.token
            else None,
        )
        self.db.add(server)
        await self.db.flush()
        await refresh_server(self.db, server, self.settings)
        await AuditService(self.db).record(
            "mcp.server_added",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="mcp_server",
            resource_id=str(server.id),
            details={"name": server.name, "status": server.status},
        )
        await bus.commit(self.db)
        return await server_out(self.db, server)

    async def update(
        self, user_id: uuid.UUID, server_id: uuid.UUID, data: McpServerUpdate
    ) -> McpServerOut:
        server = await self._get(user_id, server_id)
        changed = []
        if data.name is not None:
            server.name = data.name.strip()
            changed.append("name")
        if data.url is not None and data.url != server.url:
            server.url = data.url.strip()
            changed.append("url")
        if data.clear_token:
            server.secret_encrypted = None
            changed.append("token_cleared")
        if data.token is not None:
            server.secret_encrypted = secret_box(self.settings).encrypt(
                data.token.get_secret_value()
            )
            changed.append("token")
        if data.enabled is not None:
            server.enabled = data.enabled
            changed.append("enabled")
        if {"url", "token", "token_cleared"} & set(changed):
            # A different server (or identity) may expose different tools: re-check them all.
            for row in (
                await self.db.execute(select(Tool).where(Tool.server_id == server.id))
            ).scalars():
                row.enabled = False
            await refresh_server(self.db, server, self.settings)
        await AuditService(self.db).record(
            "mcp.server_updated",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="mcp_server",
            resource_id=str(server.id),
            details={"changed": changed},
        )
        await bus.commit(self.db)
        return await server_out(self.db, server)

    async def refresh(self, user_id: uuid.UUID, server_id: uuid.UUID) -> McpServerOut:
        server = await self._get(user_id, server_id)
        await refresh_server(self.db, server, self.settings)
        await bus.commit(self.db)
        return await server_out(self.db, server)

    async def delete(self, user_id: uuid.UUID, server_id: uuid.UUID) -> None:
        server = await self._get(user_id, server_id)
        await AuditService(self.db).record(
            "mcp.server_removed",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="mcp_server",
            resource_id=str(server.id),
            details={"name": server.name},
        )
        await self.db.delete(server)  # its tools go with it (FK cascade)
        await bus.commit(self.db)
