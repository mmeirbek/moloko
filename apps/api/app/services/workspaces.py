"""Workspace records: which directory a task works in, and what changed there (spec 16)."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import TERMINAL_TASK
from app.core.config import Settings
from app.core.errors import NotFound
from app.models.agent import Agent
from app.models.task import Task
from app.models.tooling import Workspace, WorkspaceFile
from app.services.audit import AuditService


def workspace_dir(settings: Settings, workspace_id: uuid.UUID) -> Path:
    return Path(settings.workspace_root) / str(workspace_id)


async def root_task(db: AsyncSession, task: Task) -> Task:
    current = task
    for _ in range(10):  # depth is limited (spec 7.2); guard against cycles anyway
        if current.parent_task_id is None:
            return current
        parent = await db.get(Task, current.parent_task_id)
        if parent is None:
            return current
        current = parent
    return current


async def workspace_for_task(db: AsyncSession, settings: Settings, task_id: uuid.UUID) -> Workspace:
    """The workspace of a task: the root task's agent's project workspace, or one
    workspace per root task (shared by its subagents). Created on first use."""
    task = await db.get(Task, task_id)
    if task is None:
        raise NotFound("Task not found.")
    root = await root_task(db, task)
    agent = await db.get(Agent, root.agent_id) if root.agent_id else None
    if agent is not None and agent.workspace_id is not None:
        ws = await db.get(Workspace, agent.workspace_id)
        if ws is not None:
            workspace_dir(settings, ws.id).mkdir(parents=True, exist_ok=True)
            return ws
    ws = (
        await db.execute(
            select(Workspace).where(Workspace.kind == "task", Workspace.task_id == root.id)
        )
    ).scalar_one_or_none()
    if ws is None:
        ws = Workspace(user_id=root.user_id, name=root.title[:100], kind="task", task_id=root.id)
        db.add(ws)
        await db.flush()
    workspace_dir(settings, ws.id).mkdir(parents=True, exist_ok=True)
    return ws


def sha256_of(path: Path, limit: int) -> str | None:
    if path.stat().st_size > limit:
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class FileState:
    size: int
    mtime_ns: int


def snapshot(root: Path, max_files: int) -> dict[str, FileState]:
    """Regular files under ``root`` (symlinks are not followed) — to detect changes."""
    found: dict[str, FileState] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for name in filenames:
            full = os.path.join(dirpath, name)
            st = os.lstat(full)
            if stat.S_ISREG(st.st_mode):
                found[os.path.relpath(full, root)] = FileState(st.st_size, st.st_mtime_ns)
                if len(found) >= max_files:
                    return found
    return found


def changed_paths(
    before: dict[str, FileState], after: dict[str, FileState]
) -> tuple[list[str], list[str]]:
    changed = [p for p, s in after.items() if before.get(p) != s]
    deleted = [p for p in before if p not in after]
    return sorted(changed), sorted(deleted)


async def record_changes(
    db: AsyncSession,
    settings: Settings,
    *,
    workspace: Workspace,
    changed: list[str],
    deleted: list[str],
    task_id: uuid.UUID | None,
    agent_id: uuid.UUID | None,
    tool_call_id: uuid.UUID | None,
) -> None:
    """Upsert file metadata and write one audit entry for the change set."""
    root = workspace_dir(settings, workspace.id)
    now = datetime.now(UTC)
    for rel in changed:
        full = root / rel
        try:
            st = os.lstat(full)
        except FileNotFoundError:
            continue
        digest = (
            sha256_of(full, settings.workspace_max_file_bytes) if stat.S_ISREG(st.st_mode) else None
        )
        values = {
            "id": uuid.uuid4(),
            "workspace_id": workspace.id,
            "path": rel,
            "size": st.st_size,
            "sha256": digest,
            "deleted": False,
            "last_task_id": task_id,
            "last_agent_id": agent_id,
            "last_tool_call_id": tool_call_id,
            "created_at": now,
            "updated_at": now,
        }
        stmt = insert(WorkspaceFile).values(**values)
        update = {
            k: stmt.excluded[k]
            for k in (
                "size",
                "sha256",
                "deleted",
                "last_task_id",
                "last_agent_id",
                "last_tool_call_id",
                "updated_at",
            )
        }
        await db.execute(
            stmt.on_conflict_do_update(index_elements=["workspace_id", "path"], set_=update)
        )
    for rel in deleted:
        row = (
            await db.execute(
                select(WorkspaceFile).where(
                    WorkspaceFile.workspace_id == workspace.id, WorkspaceFile.path == rel
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            row.deleted = True
            row.last_task_id, row.last_agent_id, row.last_tool_call_id = (
                task_id,
                agent_id,
                tool_call_id,
            )
    if changed or deleted:
        await AuditService(db).record(
            "workspace.files_changed",
            "success",
            actor_type="agent" if agent_id else "user",
            actor_id=agent_id,
            user_id=workspace.user_id,
            resource_type="workspace",
            resource_id=str(workspace.id),
            details={
                "changed": changed[:50],
                "deleted": deleted[:50],
                "count": len(changed) + len(deleted),
                "task_id": str(task_id) if task_id else None,
                "tool_call_id": str(tool_call_id) if tool_call_id else None,
            },
        )


async def clean_task_workspaces(db: AsyncSession, settings: Settings) -> int:
    """Delete files of task workspaces whose root task finished long enough ago (spec 16)."""
    if settings.workspace_task_ttl_days <= 0:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=settings.workspace_task_ttl_days)
    rows = (
        await db.execute(
            select(Workspace, Task)
            .join(Task, Task.id == Workspace.task_id)
            .where(
                Workspace.kind == "task",
                Workspace.cleaned_at.is_(None),
                Task.status.in_([s.value for s in TERMINAL_TASK]),
                Task.updated_at < cutoff,
            )
            .limit(100)
        )
    ).all()
    cleaned = 0
    for ws, task in rows:
        shutil.rmtree(workspace_dir(settings, ws.id), ignore_errors=True)
        ws.cleaned_at = datetime.now(UTC)
        await AuditService(db).record(
            "workspace.cleaned",
            "success",
            actor_type="system",
            user_id=ws.user_id,
            resource_type="workspace",
            resource_id=str(ws.id),
            details={"task_id": str(task.id), "ttl_days": settings.workspace_task_ttl_days},
        )
        cleaned += 1
    return cleaned


# --- browsing (owner UI) ---------------------------------------------------------------------

VIEW_LIMIT = 200_000


class WorkspaceService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db, self.settings = db, settings

    async def get(self, user_id: uuid.UUID, workspace_id: uuid.UUID) -> Workspace:
        ws = await self.db.get(Workspace, workspace_id)
        if ws is None or ws.user_id != user_id:
            raise NotFound("Workspace not found.")
        return ws

    async def list_workspaces(
        self, user_id: uuid.UUID, kind: str | None, limit: int
    ) -> list[Workspace]:
        query = select(Workspace).where(Workspace.user_id == user_id)
        if kind:
            query = query.where(Workspace.kind == kind)
        rows = await self.db.execute(query.order_by(Workspace.created_at.desc()).limit(limit))
        return list(rows.scalars())

    async def create_project(self, user_id: uuid.UUID, name: str) -> Workspace:
        ws = Workspace(user_id=user_id, name=name.strip(), kind="project")
        self.db.add(ws)
        await self.db.flush()
        workspace_dir(self.settings, ws.id).mkdir(parents=True, exist_ok=True)
        await AuditService(self.db).record(
            "workspace.created",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="workspace",
            resource_id=str(ws.id),
            details={"name": ws.name},
        )
        await self.db.commit()
        return ws

    async def for_task(self, user_id: uuid.UUID, task_id: uuid.UUID) -> Workspace | None:
        task = await self.db.get(Task, task_id)
        if task is None or task.user_id != user_id:
            raise NotFound("Task not found.")
        root = await root_task(self.db, task)
        agent = await self.db.get(Agent, root.agent_id) if root.agent_id else None
        if agent is not None and agent.workspace_id:
            return await self.db.get(Workspace, agent.workspace_id)
        return (
            await self.db.execute(
                select(Workspace).where(Workspace.kind == "task", Workspace.task_id == root.id)
            )
        ).scalar_one_or_none()

    def entries(self, ws: Workspace, rel: str) -> list[dict[str, object]]:
        from app.workspaces.paths import relative, resolve

        root = workspace_dir(self.settings, ws.id)
        if not root.exists():
            return []
        base = resolve(root, rel, must_exist=True)
        out: list[dict[str, object]] = []
        for entry in sorted(
            os.scandir(base), key=lambda e: (not e.is_dir(follow_symlinks=False), e.name)
        ):
            st = entry.stat(follow_symlinks=False)
            kind = (
                "link"
                if entry.is_symlink()
                else "dir"
                if entry.is_dir(follow_symlinks=False)
                else "file"
            )
            out.append(
                {
                    "path": relative(root, Path(entry.path)),
                    "type": kind,
                    "size": st.st_size if kind == "file" else 0,
                    "modified_at": datetime.fromtimestamp(st.st_mtime, UTC),
                }
            )
            if len(out) >= 1000:
                break
        return out

    def read(self, ws: Workspace, rel: str) -> dict[str, object]:
        from app.tools.base import ScopeError
        from app.workspaces.paths import relative, resolve

        root = workspace_dir(self.settings, ws.id)
        path = resolve(root, rel, must_exist=True)
        if not path.is_file():
            raise ScopeError("not a file")
        size = path.stat().st_size
        with path.open("rb") as fh:
            data = fh.read(VIEW_LIMIT)
        if b"\x00" in data[:8192]:
            text, truncated = "(binary file)", False
        else:
            text, truncated = data.decode("utf-8", "replace"), size > VIEW_LIMIT
        return {"path": relative(root, path), "size": size, "content": text, "truncated": truncated}
