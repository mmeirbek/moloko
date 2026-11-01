"""Sprint 7 routes: tools, approvals, integrations (GitHub, MCP), workspaces, audit log."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from app.api.deps import CurrentAuth, DbSession, QueueDep, SettingsDep
from app.core.errors import AppError, NotFound
from app.models.task import Task
from app.models.tooling import ToolCall
from app.repositories.audit_logs import AuditLogRepository
from app.schemas.tooling import (
    ApprovalOut,
    AuditOut,
    AuditPage,
    GitHubIntegrationOut,
    GitHubIntegrationUpdate,
    IntegrationsStatus,
    McpServerCreate,
    McpServerOut,
    McpServerUpdate,
    ToolCallOut,
    ToolOut,
    ToolUpdate,
    WorkspaceCreate,
    WorkspaceEntry,
    WorkspaceFileContent,
    WorkspaceOut,
)
from app.services.approvals import ApprovalService, payloads
from app.services.integrations import IntegrationService
from app.services.mcp import McpService
from app.services.tools import ToolsService
from app.services.workspaces import WorkspaceService
from app.tools.base import ScopeError
from app.tools.runner import PREVIEW_CHARS, preview_args
from app.workers.jobs import make_sandbox

tools_router = APIRouter(prefix="/tools", tags=["tools"])
approvals_router = APIRouter(prefix="/approvals", tags=["approvals"])
integrations_router = APIRouter(prefix="/integrations", tags=["integrations"])
mcp_router = APIRouter(prefix="/mcp-servers", tags=["integrations"])
workspaces_router = APIRouter(prefix="/workspaces", tags=["workspaces"])
audit_router = APIRouter(prefix="/audit", tags=["audit"])
task_tools_router = APIRouter(prefix="/tasks", tags=["tasks"])


EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class InvalidPath(AppError):
    status_code = 422
    code = "invalid_path"
    message = "This path is not allowed."


# --- tools -------------------------------------------------------------------------------


@tools_router.get("", response_model=list[ToolOut])
async def list_tools(ctx: CurrentAuth, db: DbSession, settings: SettingsDep) -> list[ToolOut]:
    return await ToolsService(db, settings).list_tools(ctx.user.id)


@tools_router.patch("/{name}", response_model=ToolOut)
async def update_tool(
    name: str, body: ToolUpdate, ctx: CurrentAuth, db: DbSession, settings: SettingsDep
) -> ToolOut:
    return await ToolsService(db, settings).update(ctx.user.id, name, body)


# --- approvals ------------------------------------------------------------------------------


@approvals_router.get("", response_model=list[ApprovalOut])
async def list_approvals(
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    queue: QueueDep,
    status_filter: str | None = Query(
        None, alias="status", pattern="^(pending|approved|rejected|expired|cancelled)$"
    ),
    task_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> list[ApprovalOut]:
    rows = await ApprovalService(db, settings, queue).list_approvals(
        ctx.user.id, status=status_filter, task_id=task_id, limit=limit
    )
    return [ApprovalOut.model_validate(p) for p in await payloads(db, rows)]


async def _one(db: DbSession, approval: object) -> ApprovalOut:
    return ApprovalOut.model_validate((await payloads(db, [approval]))[0])  # type: ignore[list-item]


@approvals_router.get("/{approval_id}", response_model=ApprovalOut)
async def get_approval(
    approval_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, settings: SettingsDep, queue: QueueDep
) -> ApprovalOut:
    return await _one(db, await ApprovalService(db, settings, queue).get(ctx.user.id, approval_id))


@approvals_router.post(
    "/{approval_id}/approve", response_model=ApprovalOut, summary="Approve this ONE operation"
)
async def approve(
    approval_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, settings: SettingsDep, queue: QueueDep
) -> ApprovalOut:
    return await _one(
        db, await ApprovalService(db, settings, queue).decide(ctx.user.id, approval_id, True)
    )


@approvals_router.post("/{approval_id}/reject", response_model=ApprovalOut)
async def reject(
    approval_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, settings: SettingsDep, queue: QueueDep
) -> ApprovalOut:
    return await _one(
        db, await ApprovalService(db, settings, queue).decide(ctx.user.id, approval_id, False)
    )


@approvals_router.post(
    "/{approval_id}/cancel-task", response_model=ApprovalOut, summary="Reject and cancel the task"
)
async def cancel_task(
    approval_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, settings: SettingsDep, queue: QueueDep
) -> ApprovalOut:
    return await _one(
        db, await ApprovalService(db, settings, queue).cancel_task(ctx.user.id, approval_id)
    )


# --- integrations -----------------------------------------------------------------------------


@integrations_router.get("/status", response_model=IntegrationsStatus)
async def integrations_status(
    ctx: CurrentAuth, db: DbSession, settings: SettingsDep
) -> IntegrationsStatus:
    return await IntegrationService(db, settings).status(ctx.user.id, make_sandbox(settings))


@integrations_router.get("/github", response_model=GitHubIntegrationOut)
async def get_github(
    ctx: CurrentAuth, db: DbSession, settings: SettingsDep
) -> GitHubIntegrationOut:
    return await IntegrationService(db, settings).github(ctx.user.id)


@integrations_router.put(
    "/github", response_model=GitHubIntegrationOut, summary="Set token / allowed repositories"
)
async def put_github(
    body: GitHubIntegrationUpdate, ctx: CurrentAuth, db: DbSession, settings: SettingsDep
) -> GitHubIntegrationOut:
    return await IntegrationService(db, settings).update_github(ctx.user.id, body)


@integrations_router.post("/github/test", response_model=GitHubIntegrationOut)
async def test_github(
    ctx: CurrentAuth, db: DbSession, settings: SettingsDep
) -> GitHubIntegrationOut:
    return await IntegrationService(db, settings).test_github(ctx.user.id)


@mcp_router.get("", response_model=list[McpServerOut])
async def list_mcp(ctx: CurrentAuth, db: DbSession, settings: SettingsDep) -> list[McpServerOut]:
    return await McpService(db, settings).list_servers(ctx.user.id)


@mcp_router.post(
    "",
    response_model=McpServerOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a server (its tools start disabled)",
)
async def add_mcp(
    body: McpServerCreate, ctx: CurrentAuth, db: DbSession, settings: SettingsDep
) -> McpServerOut:
    return await McpService(db, settings).create(ctx.user.id, body)


@mcp_router.patch("/{server_id}", response_model=McpServerOut)
async def update_mcp(
    server_id: uuid.UUID,
    body: McpServerUpdate,
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
) -> McpServerOut:
    return await McpService(db, settings).update(ctx.user.id, server_id, body)


@mcp_router.post(
    "/{server_id}/refresh", response_model=McpServerOut, summary="Reconnect and list tools"
)
async def refresh_mcp(
    server_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, settings: SettingsDep
) -> McpServerOut:
    return await McpService(db, settings).refresh(ctx.user.id, server_id)


@mcp_router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp(
    server_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, settings: SettingsDep
) -> Response:
    await McpService(db, settings).delete(ctx.user.id, server_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- workspaces ---------------------------------------------------------------------------------


@workspaces_router.get("", response_model=list[WorkspaceOut])
async def list_workspaces(
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    kind: str | None = Query(None, pattern="^(task|project)$"),
    limit: int = Query(50, ge=1, le=200),
) -> list[WorkspaceOut]:
    rows = await WorkspaceService(db, settings).list_workspaces(ctx.user.id, kind, limit)
    return [WorkspaceOut.model_validate(w) for w in rows]


@workspaces_router.post(
    "",
    response_model=WorkspaceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project workspace",
)
async def create_workspace(
    body: WorkspaceCreate, ctx: CurrentAuth, db: DbSession, settings: SettingsDep
) -> WorkspaceOut:
    return WorkspaceOut.model_validate(
        await WorkspaceService(db, settings).create_project(ctx.user.id, body.name)
    )


@workspaces_router.get("/{workspace_id}/files", response_model=list[WorkspaceEntry])
async def workspace_files(
    workspace_id: uuid.UUID,
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    path: str = Query(".", max_length=512),
) -> list[WorkspaceEntry]:
    service = WorkspaceService(db, settings)
    ws = await service.get(ctx.user.id, workspace_id)
    try:
        return [WorkspaceEntry.model_validate(e) for e in service.entries(ws, path)]
    except ScopeError as exc:
        raise InvalidPath(str(exc)) from None


@workspaces_router.get("/{workspace_id}/file", response_model=WorkspaceFileContent)
async def workspace_file(
    workspace_id: uuid.UUID,
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    path: str = Query(..., max_length=512),
) -> WorkspaceFileContent:
    service = WorkspaceService(db, settings)
    ws = await service.get(ctx.user.id, workspace_id)
    try:
        return WorkspaceFileContent.model_validate(service.read(ws, path))
    except ScopeError as exc:
        raise InvalidPath(str(exc)) from None


@task_tools_router.get("/{task_id}/workspace", response_model=WorkspaceOut | None)
async def task_workspace(
    task_id: uuid.UUID, ctx: CurrentAuth, db: DbSession, settings: SettingsDep
) -> WorkspaceOut | None:
    ws = await WorkspaceService(db, settings).for_task(ctx.user.id, task_id)
    return WorkspaceOut.model_validate(ws) if ws else None


@task_tools_router.get(
    "/{task_id}/tool-calls",
    response_model=list[ToolCallOut],
    summary="Commands run, files changed, errors and results of a task",
)
async def task_tool_calls(task_id: uuid.UUID, ctx: CurrentAuth, db: DbSession) -> list[ToolCallOut]:
    task = await db.get(Task, task_id)
    if task is None or task.user_id != ctx.user.id:
        raise NotFound("Task not found.")
    rows = await db.execute(
        select(ToolCall).where(ToolCall.task_id == task_id).order_by(ToolCall.created_at)
    )
    out = []
    for row in rows.scalars():
        item = ToolCallOut.model_validate(row)
        item.args = preview_args(row.args)
        if item.result and len(item.result) > PREVIEW_CHARS * 2:
            item.result = item.result[: PREVIEW_CHARS * 2] + "…"
        out.append(item)
    return out


# --- audit log -----------------------------------------------------------------------------------


@audit_router.get("", response_model=AuditPage, summary="The audit journal (newest first)")
async def audit_log(
    ctx: CurrentAuth,
    db: DbSession,
    action: str | None = Query(
        None, max_length=64, description="action prefix, e.g. tool. or approval."
    ),
    outcome: str | None = Query(None, pattern="^(success|failure|denied)$"),
    cursor: str | None = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=200),
) -> AuditPage:
    before = None
    if cursor:
        try:
            micros, _, raw_id = cursor.partition("_")
            before = (EPOCH + timedelta(microseconds=int(micros)), uuid.UUID(raw_id))
        except ValueError:
            raise AppError("Invalid cursor.", code="invalid_cursor", status_code=422) from None
    rows = await AuditLogRepository(db).page(
        user_id=ctx.user.id, action_prefix=action, outcome=outcome, before=before, limit=limit + 1
    )
    items = [AuditOut.model_validate(r) for r in rows[:limit]]
    last = rows[limit - 1] if len(rows) > limit else None
    next_cursor = (
        f"{(last.created_at - EPOCH) // timedelta(microseconds=1)}_{last.id}" if last else None
    )
    return AuditPage(items=items, next_cursor=next_cursor)
