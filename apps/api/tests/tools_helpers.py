"""Helpers for tool tests: scripted model replies and agent setup."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from app.models import Approval, AuditLog, ToolCall
from app.providers.base import ChatRequest, ChatResult
from app.providers.base import ToolCall as ModelToolCall
from tests.conftest import add_mock_model, create_agent, csrf_headers

Step = tuple[str, dict[str, Any]] | str


def scripted(*steps: Step) -> Any:
    """Model replies by turn: a (tool, args) pair = call a tool; a string = final answer.
    The turn is the number of assistant messages so far."""

    def handler(req: ChatRequest) -> ChatResult | None:
        turn = sum(1 for m in req.messages if m.role == "assistant")
        step = steps[min(turn, len(steps) - 1)]
        if isinstance(step, str):
            return ChatResult(text=step)
        name, args = step
        return ChatResult(text="", tool_calls=(ModelToolCall(f"call_{turn}", name, args),))

    return handler


async def tool_agent(
    client: httpx.AsyncClient, *, autonomy: str = "balanced", tools: list[str], **extra: Any
) -> dict[str, Any]:
    await add_mock_model(client)
    return await create_agent(client, autonomy_level=autonomy, allowed_tools=tools, **extra)


async def tool_calls(app: FastAPI, task_id: str) -> list[ToolCall]:
    async with app.state.db.sessionmaker() as db:
        rows = await db.execute(
            select(ToolCall)
            .where(ToolCall.task_id == uuid.UUID(task_id))
            .order_by(ToolCall.created_at)
        )
        return list(rows.scalars())


async def approvals(app: FastAPI, task_id: str) -> list[Approval]:
    async with app.state.db.sessionmaker() as db:
        rows = await db.execute(
            select(Approval)
            .where(Approval.task_id == uuid.UUID(task_id))
            .order_by(Approval.created_at)
        )
        return list(rows.scalars())


async def audit_actions(app: FastAPI, prefix: str) -> list[AuditLog]:
    async with app.state.db.sessionmaker() as db:
        rows = await db.execute(
            select(AuditLog).where(AuditLog.action.like(prefix + "%")).order_by(AuditLog.created_at)
        )
        return list(rows.scalars())


async def decide(client: httpx.AsyncClient, approval_id: Any, action: str) -> httpx.Response:
    return await client.post(
        f"/api/v1/approvals/{approval_id}/{action}", headers=await csrf_headers(client)
    )
