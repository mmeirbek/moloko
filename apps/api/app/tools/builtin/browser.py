"""``browser_screenshot``: open a public web page in the sandbox's headless browser, save a
screenshot into the workspace and return the page text. **Sensitive** — always needs the
owner's approval (spec 15, owner request). The browser runs in its own locked-down
container whose only way out is the egress proxy (public addresses only)."""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from app.sandbox.base import SandboxUnavailable
from app.services.workspaces import record_changes, workspace_dir
from app.tools.base import (
    BaseTool,
    OperationInfo,
    ScopeError,
    ToolCategory,
    ToolContext,
    ToolFailed,
    ToolOutput,
    object_schema,
    string_prop,
)
from app.tools.builtin.web import check_url, html_to_text

REFUSED_MARK = "moloko egress:"
TEXT_LIMIT = 12_000


def screenshot_name(url: str, now: datetime | None = None) -> str:
    host = re.sub(r"[^a-z0-9.-]", "-", (urlsplit(url).hostname or "page").lower())[:50]
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    return f"screenshots/{host}-{stamp}.png"


class BrowserScreenshot(BaseTool):
    name = "browser_screenshot"
    title = "Open a web page (browser)"
    description = (
        "Open a public web page in a real (headless) browser, including pages that need "
        "JavaScript. Saves a screenshot to screenshots/ in your workspace and returns the "
        "page's title and text."
    )
    group = "web"
    category = ToolCategory.SENSITIVE
    input_schema = object_schema(
        {
            "url": string_prop("http(s) URL of the page", maxLength=2000),
            "full_height": {"type": "boolean", "description": "Taller screenshot (2400 px)"},
        },
        ["url"],
    )

    async def check_scope(self, ctx: ToolContext, args: dict[str, Any]) -> None:
        if ctx.sandbox is None:
            raise ScopeError("the sandbox is not configured")
        await check_url(args["url"], ctx.settings)  # public address and allowed port only

    def describe(self, args: dict[str, Any]) -> OperationInfo:
        return OperationInfo(
            summary=f"Open in the browser: {args['url'][:200]}",
            resources=[urlsplit(args["url"]).hostname or args["url"][:100]],
            consequences=(
                "The page is loaded from the internet by the sandbox browser (it may run the "
                "site's scripts); a screenshot is saved in the workspace."
            ),
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        assert ctx.sandbox is not None
        ws = await ctx.workspace()
        shot = screenshot_name(args["url"])
        dom = f".browser/{secrets.token_hex(8)}.html"
        root = workspace_dir(ctx.settings, ws.id)
        (root / "screenshots").mkdir(parents=True, exist_ok=True)
        (root / ".browser").mkdir(parents=True, exist_ok=True)
        try:
            result = await ctx.sandbox.browse(
                ws.id,
                {
                    "mode": "page",
                    "url": args["url"],
                    "screenshot": shot,
                    "dom": dom,
                    "width": 1280,
                    "height": 2400 if args.get("full_height") else 900,
                },
            )
        except SandboxUnavailable as exc:
            raise ToolFailed(str(exc)) from None
        html = ""
        dom_path = root / dom
        try:
            if dom_path.is_file() and not dom_path.is_symlink():
                html = dom_path.read_text(encoding="utf-8", errors="replace")
        finally:
            dom_path.unlink(missing_ok=True)
        if result.timed_out:
            raise ToolFailed("The page took too long to load.")
        if REFUSED_MARK in html:
            raise ToolFailed("The page (or a redirect) points to a private or local address.")
        if result.exit_code != 0 or not (root / shot).is_file():
            raise ToolFailed("The browser could not open the page.")
        async with ctx.sessionmaker() as db:
            await record_changes(
                db,
                ctx.settings,
                workspace=ws,
                changed=[shot],
                deleted=[],
                task_id=ctx.task_id,
                agent_id=ctx.agent.id,
                tool_call_id=ctx.tool_call_id,
            )
            await db.commit()
        title, text = html_to_text(html)
        body = text[:TEXT_LIMIT].replace("</page", "&lt;/page")
        return ToolOutput(
            f"Opened {args['url']}\nTitle: {title}\nScreenshot saved: {shot}\n\n"
            f'<page url="{args["url"][:300]}" trust="untrusted">\n{body}\n</page>'
        )


BROWSER_TOOLS: tuple[BaseTool, ...] = (BrowserScreenshot(),)
