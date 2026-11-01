"""MCP Manager plumbing (spec 15.5): connect to a server over Streamable HTTP, list its
tools, call one. Every call opens a fresh short session with a timeout, so a server that
goes down only fails that call. MCP output is untrusted content."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx2
from mcp import Client
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.crypto import DecryptionFailed, EncryptionUnavailable, secret_box
from app.models.tooling import McpServer, Tool
from app.tools.base import BaseTool, ToolCategory, ToolContext, ToolFailed, ToolOutput

ClientFactory = Callable[[McpServer, str | None, Settings], Client]


def _http_client(server: McpServer, token: str | None, settings: Settings) -> Client:
    from mcp.client.streamable_http import streamable_http_client

    headers = {str(k): str(v) for k, v in (server.headers or {}).items()}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    http = httpx2.AsyncClient(headers=headers, timeout=settings.mcp_timeout_seconds)
    return Client(
        streamable_http_client(server.url, http_client=http),
        read_timeout_seconds=settings.mcp_timeout_seconds,
    )


CLIENT_FACTORY: ClientFactory = _http_client  # tests connect in-process instead


class McpUnavailable(Exception):
    pass


def tool_name(slug: str, remote: str) -> str:
    """Provider-safe unique name: ``mcp_<slug>_<tool>`` (letters, digits, _ and -, ≤ 64)."""
    clean = re.sub(r"[^A-Za-z0-9_-]", "_", remote)
    return f"mcp_{slug}_{clean}"[:64]


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", name.lower())[:16]
    return slug or "server"


async def server_token(db: AsyncSession, server: McpServer, settings: Settings) -> str | None:
    """The bearer token: stored with the server, or the GitHub integration's token."""
    if server.auth_source == "github":
        from app.integrations.github import access_for

        access = await access_for(db, settings, server.user_id)
        if access is None:
            raise McpUnavailable("GitHub is not connected (Integrations → GitHub).")
        return access.token
    if not server.secret_encrypted:
        return None
    try:
        return secret_box(settings).decrypt(server.secret_encrypted)
    except (EncryptionUnavailable, DecryptionFailed):
        raise McpUnavailable(
            "The server's token cannot be decrypted (APP_ENCRYPTION_KEY)."
        ) from None


def suggested_category(tool: Any) -> str:
    """MCP annotations are hints from the server (untrusted): read-only tools are suggested
    as ``read``, everything else as ``sensitive``. Tools stay OFF until the owner decides."""
    annotations = getattr(tool, "annotations", None)
    if annotations is not None and getattr(annotations, "read_only_hint", None) is True:
        return ToolCategory.READ.value
    return ToolCategory.SENSITIVE.value


async def list_remote_tools(
    server: McpServer, settings: Settings, token: str | None
) -> tuple[dict[str, Any], list[Any]]:
    try:
        async with CLIENT_FACTORY(server, token, settings) as client:
            info = client.server_info
            tools: list[Any] = []
            cursor = None
            for _ in range(20):
                page = await client.list_tools(cursor=cursor)
                tools.extend(page.tools)
                cursor = page.next_cursor
                if not cursor:
                    break
    except McpUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 — any transport/protocol failure = server unavailable
        raise McpUnavailable(f"Cannot talk to the MCP server ({type(exc).__name__}).") from None
    meta = (
        {"name": getattr(info, "name", None), "version": getattr(info, "version", None)}
        if info
        else {}
    )
    return meta, tools


async def refresh_server(db: AsyncSession, server: McpServer, settings: Settings) -> list[Tool]:
    """Connect, list tools and store them. New tools start DISABLED (never auto-trust)."""
    now = datetime.now(UTC)
    try:
        meta, remote = await list_remote_tools(
            server, settings, await server_token(db, server, settings)
        )
    except McpUnavailable as exc:
        server.status, server.last_error, server.last_checked_at = "error", str(exc)[:500], now
        rows = (await db.execute(select(Tool).where(Tool.server_id == server.id))).scalars()
        return list(rows)
    server.status, server.last_error, server.last_checked_at, server.server_info = (
        "ok",
        None,
        now,
        meta,
    )
    existing = {
        t.remote_name: t
        for t in (await db.execute(select(Tool).where(Tool.server_id == server.id))).scalars()
    }
    seen: set[str] = set()
    for item in remote:
        seen.add(item.name)
        schema = item.input_schema if isinstance(item.input_schema, dict) else {"type": "object"}
        row = existing.get(item.name)
        if row is None:
            row = Tool(
                user_id=server.user_id,
                name=tool_name(server.slug, item.name),
                source="mcp",
                server_id=server.id,
                remote_name=item.name,
                description=(item.description or "")[:2000],
                category=suggested_category(item),
                input_schema=schema,
                enabled=False,
                available=True,
            )
            db.add(row)
            existing[item.name] = row
        else:
            changed_schema = row.input_schema != schema
            row.description, row.input_schema, row.available = (
                (item.description or "")[:2000],
                schema,
                True,
            )
            if changed_schema:
                row.enabled = False  # a changed tool must be re-approved by the owner
    for name, row in existing.items():
        if name not in seen:
            row.available = False
    await db.flush()
    return list(existing.values())


class McpTool(BaseTool):
    group = "mcp"

    def __init__(self, row: Tool, server: McpServer) -> None:
        self.row, self.server = row, server
        self.name = row.name
        self.title = f"{server.name}: {row.remote_name}"
        self.description = f"[MCP {server.name}] {row.description}"[:2000]
        self.category = ToolCategory(row.category or ToolCategory.SENSITIVE.value)
        schema = dict(row.input_schema or {})
        schema.setdefault("type", "object")
        self.input_schema = schema

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        try:
            async with ctx.sessionmaker() as db:
                token = await server_token(db, self.server, ctx.settings)
            async with CLIENT_FACTORY(self.server, token, ctx.settings) as client:
                result = await client.call_tool(self.row.remote_name or "", args)
        except McpUnavailable as exc:
            raise ToolFailed(str(exc)) from None
        except Exception as exc:  # noqa: BLE001
            raise ToolFailed(
                f"The MCP server '{self.server.name}' is unavailable ({type(exc).__name__})."
            ) from None
        parts: list[str] = []
        for block in result.content:
            text = getattr(block, "text", None)
            parts.append(
                text if isinstance(text, str) else f"[{getattr(block, 'type', 'content')} omitted]"
            )
        return ToolOutput("\n".join(parts) or "(no output)", is_error=bool(result.is_error))
