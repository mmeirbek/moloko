"""File tools inside the task's workspace (spec 15.6 File system).

read/list are ``read``; write/move are ``write`` (a move that replaces an existing file is
``sensitive``); delete is always ``sensitive`` (needs approval).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import stat
from pathlib import Path
from typing import Any

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
from app.workspaces.paths import relative, resolve

MAX_LIST = 500


async def _root(ctx: ToolContext) -> Path:
    ws = await ctx.workspace()
    return workspace_dir(ctx.settings, ws.id)


async def _record(ctx: ToolContext, changed: list[str], deleted: list[str]) -> None:
    ws = await ctx.workspace()
    async with ctx.sessionmaker() as db:
        await record_changes(
            db,
            ctx.settings,
            workspace=ws,
            changed=changed,
            deleted=deleted,
            task_id=ctx.task_id,
            agent_id=ctx.agent.id,
            tool_call_id=ctx.tool_call_id,
        )
        await db.commit()


class FsList(BaseTool):
    name = "fs_list"
    title = "List files"
    description = "List files and folders in the task workspace."
    group = "files"
    category = ToolCategory.READ
    input_schema = object_schema(
        {
            "path": string_prop("Folder relative to the workspace root", default="."),
            "recursive": {"type": "boolean", "default": False},
        },
        [],
    )

    async def check_scope(self, ctx: ToolContext, args: dict[str, Any]) -> None:
        resolve(await _root(ctx), args.get("path", "."))

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        root = await _root(ctx)
        base = resolve(root, args.get("path", "."), must_exist=True)
        recursive = bool(args.get("recursive"))

        def listing() -> list[str]:
            if not base.is_dir():
                raise ToolFailed("Not a folder.")
            out: list[str] = []
            walker = os.walk(base, followlinks=False) if recursive else [(str(base), *_one(base))]
            for dirpath, dirnames, filenames in walker:
                for d in sorted(dirnames):
                    out.append(relative(root, Path(dirpath) / d) + "/")
                for f in sorted(filenames):
                    full = Path(dirpath) / f
                    st = os.lstat(full)
                    kind = " -> (link)" if stat.S_ISLNK(st.st_mode) else f" ({st.st_size} bytes)"
                    out.append(relative(root, full) + kind)
                if len(out) >= MAX_LIST:
                    return [*out[:MAX_LIST], f"… more than {MAX_LIST} entries"]
            return out

        entries = await asyncio.to_thread(listing)
        return ToolOutput("\n".join(entries) if entries else "(empty)")


def _one(base: Path) -> tuple[list[str], list[str]]:
    dirs: list[str] = []
    files: list[str] = []
    for entry in os.scandir(base):
        (dirs if entry.is_dir(follow_symlinks=False) else files).append(entry.name)
    return dirs, files


class FsRead(BaseTool):
    name = "fs_read"
    title = "Read a file"
    description = "Read a text file from the task workspace."
    group = "files"
    category = ToolCategory.READ
    input_schema = object_schema(
        {"path": string_prop("File relative to the workspace root")}, ["path"]
    )

    async def check_scope(self, ctx: ToolContext, args: dict[str, Any]) -> None:
        resolve(await _root(ctx), args["path"])

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        path = resolve(await _root(ctx), args["path"], must_exist=True)
        limit = ctx.settings.workspace_max_file_bytes

        def read() -> str:
            if not path.is_file():
                raise ToolFailed("Not a file.")
            if path.stat().st_size > limit:
                raise ToolFailed(f"The file is larger than {limit} bytes.")
            data = path.read_bytes()
            if b"\x00" in data[:8192]:
                raise ToolFailed("This looks like a binary file.")
            return data.decode("utf-8", errors="replace")

        return ToolOutput(await asyncio.to_thread(read))


class FsWrite(BaseTool):
    name = "fs_write"
    title = "Write a file"
    description = (
        "Create or change a text file in the task workspace. mode: overwrite (default), "
        "append, or create (fails if the file exists)."
    )
    group = "files"
    category = ToolCategory.WRITE
    input_schema = object_schema(
        {
            "path": string_prop("File relative to the workspace root"),
            "content": {"type": "string"},
            "mode": {
                "type": "string",
                "enum": ["overwrite", "append", "create"],
                "default": "overwrite",
            },
        },
        ["path", "content"],
    )

    async def check_scope(self, ctx: ToolContext, args: dict[str, Any]) -> None:
        resolve(await _root(ctx), args["path"])
        if len(args["content"].encode()) > ctx.settings.workspace_max_file_bytes:
            raise ScopeError(
                f"content is larger than {ctx.settings.workspace_max_file_bytes} bytes"
            )

    def describe(self, args: dict[str, Any]) -> OperationInfo:
        mode = args.get("mode", "overwrite")
        return OperationInfo(
            summary=f"{'Append to' if mode == 'append' else 'Write'} file {args['path']} "
            f"({len(args['content'])} characters)",
            resources=[f"workspace:{args['path']}"],
            consequences="The file is created, or its current content is replaced."
            if mode != "append"
            else "Text is added to the end of the file.",
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        root = await _root(ctx)
        path = resolve(root, args["path"])
        mode = args.get("mode", "overwrite")
        content: str = args["content"]

        def write() -> str:
            if path.exists() and path.is_dir():
                raise ToolFailed("A folder with this name exists.")
            if mode == "create" and path.exists():
                raise ToolFailed("The file already exists.")
            path.parent.mkdir(parents=True, exist_ok=True)
            resolve(root, relative(root, path))  # re-check: no link appeared on the way
            flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW
            flags |= os.O_APPEND if mode == "append" else os.O_TRUNC
            fd = os.open(path, flags, 0o644)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
            return relative(root, path)

        rel = await asyncio.to_thread(write)
        await _record(ctx, [rel], [])
        return ToolOutput(f"Wrote {rel} ({path.stat().st_size} bytes).")


class FsMove(BaseTool):
    name = "fs_move"
    title = "Move or rename"
    description = "Move or rename a file or folder inside the task workspace."
    group = "files"
    category = ToolCategory.WRITE
    input_schema = object_schema(
        {
            "source": string_prop("Current path"),
            "destination": string_prop("New path"),
            "overwrite": {"type": "boolean", "default": False},
        },
        ["source", "destination"],
    )

    async def check_scope(self, ctx: ToolContext, args: dict[str, Any]) -> None:
        root = await _root(ctx)
        resolve(root, args["source"], must_exist=True)
        resolve(root, args["destination"])

    async def category_for(self, ctx: ToolContext, args: dict[str, Any]) -> ToolCategory:
        dest = resolve(await _root(ctx), args["destination"])
        return ToolCategory.SENSITIVE if dest.exists() else ToolCategory.WRITE

    def describe(self, args: dict[str, Any]) -> OperationInfo:
        return OperationInfo(
            summary=f"Move {args['source']} → {args['destination']}",
            resources=[f"workspace:{args['source']}", f"workspace:{args['destination']}"],
            consequences="If the destination exists it is replaced and its old content is lost."
            if args.get("overwrite")
            else "Fails if the destination exists.",
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        root = await _root(ctx)
        src = resolve(root, args["source"], must_exist=True)
        dest = resolve(root, args["destination"])

        def move() -> None:
            if dest.exists() and not args.get("overwrite"):
                raise ToolFailed("The destination exists (set overwrite to replace it).")
            if dest.is_dir():
                raise ToolFailed("The destination is a folder.")
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, dest)  # same filesystem: atomic rename

        await asyncio.to_thread(move)
        await _record(ctx, [relative(root, dest)], [relative(root, src)])
        return ToolOutput(f"Moved {relative(root, src)} → {relative(root, dest)}.")


class FsDelete(BaseTool):
    name = "fs_delete"
    title = "Delete a file"
    description = (
        "Delete a file or folder in the task workspace. Always needs the owner's approval."
    )
    group = "files"
    category = ToolCategory.SENSITIVE
    input_schema = object_schema(
        {"path": string_prop("File or folder"), "recursive": {"type": "boolean", "default": False}},
        ["path"],
    )

    async def check_scope(self, ctx: ToolContext, args: dict[str, Any]) -> None:
        path = resolve(await _root(ctx), args["path"], must_exist=True)
        if path == await _root(ctx):
            raise ScopeError("the workspace root cannot be deleted")

    def describe(self, args: dict[str, Any]) -> OperationInfo:
        what = "folder and everything in it" if args.get("recursive") else "file"
        return OperationInfo(
            summary=f"Delete {args['path']}",
            resources=[f"workspace:{args['path']}"],
            consequences=f"The {what} is deleted permanently.",
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        root = await _root(ctx)
        path = resolve(root, args["path"], must_exist=True)

        def delete() -> list[str]:
            if path.is_dir():
                if not args.get("recursive"):
                    raise ToolFailed("This is a folder: set recursive to delete it.")
                files = [relative(root, Path(d) / f) for d, _, fs in os.walk(path) for f in fs]
                shutil.rmtree(path)
                return files
            path.unlink()
            return [relative(root, path)]

        removed = await asyncio.to_thread(delete)
        await _record(ctx, [], removed)
        return ToolOutput(f"Deleted {args['path']} ({len(removed)} file(s)).")


FILE_TOOLS: tuple[BaseTool, ...] = (FsList(), FsRead(), FsWrite(), FsMove(), FsDelete())
