"""Export a task's result as Markdown or PDF (owner request).

Markdown is built here. PDF: the result is rendered to HTML (markdown-it, raw HTML
escaped) and printed by the sandbox browser with **no network**; the PDF is also kept in
the task's workspace (`exports/`). Without the sandbox browser the API says so
(`pdf_unavailable`) and the web app falls back to the browser's own print dialog.
"""

from __future__ import annotations

import html
import re
import secrets
import uuid
from datetime import UTC, datetime

from markdown_it import MarkdownIt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, Conflict
from app.models.task import Task
from app.sandbox.base import Sandbox, SandboxUnavailable
from app.services.workspaces import record_changes, workspace_dir, workspace_for_task


class PdfUnavailable(Conflict):
    code = "pdf_unavailable"
    message = (
        "PDF export needs the sandbox browser (docker compose --profile browser build browser)."
    )


class NothingToExport(AppError):
    status_code = 409
    code = "nothing_to_export"
    message = "This task has no result yet."


def safe_name(title: str) -> str:
    base = re.sub(r"[^\w.-]+", "-", title.strip(), flags=re.UNICODE).strip("-.")[:60]
    return base or "result"


def task_markdown(task: Task) -> str:
    when = (task.completed_at or task.updated_at or datetime.now(UTC)).strftime(
        "%Y-%m-%d %H:%M UTC"
    )
    lines = [f"# {task.title}", "", f"_moloko · {task.status} · {when}_", ""]
    if task.description.strip():
        lines += ["## Задача / Task", "", task.description.strip(), ""]
    if task.result:
        lines += ["## Результат / Result", "", task.result.strip(), ""]
    if task.error_message:
        lines += ["## Ошибка / Error", "", task.error_message, ""]
    return "\n".join(lines).rstrip() + "\n"


STYLE = """
body { font-family: "DejaVu Sans", "Noto Sans", sans-serif; color: #10142b; margin: 32px 40px;
       font-size: 12pt; line-height: 1.5; }
h1 { font-size: 20pt; margin: 0 0 4px; } h2 { font-size: 14pt; margin-top: 20px; }
em { color: #5b6078; } pre, code { font-family: "DejaVu Sans Mono", monospace; font-size: 10pt; }
pre { background: #f1ecdf; padding: 8px; white-space: pre-wrap; }
table { border-collapse: collapse; }
td, th { border: 1px solid #d6cfbb; padding: 4px 8px; } a { color: #2f86c6; }
.brand { color: #5b6078; font-size: 9pt; border-bottom: 1px solid #e2dccb; margin-bottom: 16px; }
"""


def task_html(task: Task) -> str:
    md = MarkdownIt("commonmark", {"html": False}).enable("table")  # raw HTML is escaped
    body = md.render(task_markdown(task))
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f"<title>{html.escape(task.title)}</title>"
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; style-src 'unsafe-inline'\">"
        f"<style>{STYLE}</style></head><body>"
        '<div class="brand">moloko</div>'
        f"{body}</body></html>"
    )


async def task_pdf(
    db: AsyncSession,
    settings: Settings,
    sandbox: Sandbox | None,
    task: Task,
    *,
    agent_id: uuid.UUID | None = None,
) -> tuple[str, bytes]:
    if not task.result and not task.error_message:
        raise NothingToExport()
    if sandbox is None:
        raise PdfUnavailable()
    ws = await workspace_for_task(db, settings, task.id)
    root = workspace_dir(settings, ws.id)
    source = f".browser/{secrets.token_hex(8)}.html"
    name = f"exports/{safe_name(task.title)}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.pdf"
    (root / ".browser").mkdir(parents=True, exist_ok=True)
    (root / "exports").mkdir(parents=True, exist_ok=True)
    (root / source).write_text(task_html(task), encoding="utf-8")
    try:
        result = await sandbox.browse(ws.id, {"mode": "pdf", "source": source, "pdf": name})
    except SandboxUnavailable:
        raise PdfUnavailable() from None
    finally:
        (root / source).unlink(missing_ok=True)
    pdf = root / name
    if result.exit_code != 0 or not pdf.is_file():
        raise PdfUnavailable("The browser could not print the PDF.")
    await record_changes(
        db,
        settings,
        workspace=ws,
        changed=[name],
        deleted=[],
        task_id=task.id,
        agent_id=agent_id,
        tool_call_id=None,
    )
    await db.commit()
    return name.removeprefix("exports/"), pdf.read_bytes()
