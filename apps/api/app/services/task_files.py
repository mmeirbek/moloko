"""Files the owner sends into a task's chat: they land in the task's workspace (``inbox/``)
where its agents can read them; the owner's next message names them."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import TERMINAL_TASK, InvalidTransition, TaskStatus
from app.core.config import Settings
from app.schemas.tasks import TaskFileOut
from app.services.audit import AuditService
from app.services.files import FileStore, receive_upload
from app.services.tasks import TaskService
from app.services.workspaces import workspace_dir, workspace_for_task
from app.tasks.queue import TaskEnqueuer

INBOX = "inbox"


async def receive_task_file(
    db: AsyncSession,
    queue: TaskEnqueuer | None,
    settings: Settings,
    user_id: uuid.UUID,
    task_id: uuid.UUID,
    request: Request,
) -> TaskFileOut:
    task = await TaskService(db, queue).get(user_id, task_id)
    if TaskStatus(task.status) in TERMINAL_TASK:
        raise InvalidTransition("The task has finished — continue it instead.")
    root = workspace_dir(settings, (await workspace_for_task(db, settings, task.id)).id)
    await db.commit()  # give the connection back: a big file may take minutes to arrive
    folder = root / INBOX
    received = await receive_upload(request, FileStore(settings, root=root), settings, folder)
    final = await asyncio.to_thread(_place, received.path, folder, received.filename, root)
    out = TaskFileOut(
        path=f"{INBOX}/{final.name}",
        filename=received.filename,
        size=received.size,
        content_type=received.content_type,
    )
    await AuditService(db).record(
        "task.file_received",
        "success",
        actor_type="user",
        actor_id=user_id,
        user_id=user_id,
        resource_type="task",
        resource_id=str(task_id),
        details={"path": out.path, "size": out.size},
    )
    await db.commit()
    return out


def _place(temp: Path, folder: Path, filename: str, root: Path) -> Path:
    """Move the received file to its name, never over another file: photo.png,
    photo-2.png, … In a git repository the inbox stays out of commits."""
    stem, suffix = os.path.splitext(filename)
    n = 1
    while True:
        final = folder / (filename if n == 1 else f"{stem}-{n}{suffix}")
        try:
            os.link(temp, final)  # fails if the name is taken (unlike rename)
        except FileExistsError:
            n += 1
            continue
        except OSError:  # no hard links on this disk: one writer per task, check then move
            if final.exists():
                n += 1
                continue
            os.replace(temp, final)
            break
        temp.unlink()
        break
    exclude = root / ".git" / "info" / "exclude"
    if exclude.parent.is_dir():
        lines = exclude.read_text().splitlines() if exclude.exists() else []
        if f"/{INBOX}/" not in lines:
            exclude.write_text("\n".join([*lines, f"/{INBOX}/"]) + "\n")
    return final
