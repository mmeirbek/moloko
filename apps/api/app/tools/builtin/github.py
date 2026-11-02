"""GitHub tools (spec 15.6). Reading is ``read``; creating a branch or committing to a
non-default branch is ``write``; committing to the default branch and opening a pull
request (publishing) are ``sensitive``.

``github_checkout`` downloads a repository into the agent's workspace (``write``, like
``fs_write``; ``sensitive`` when it replaces files in a folder that already has some, like
an ``fs_move`` that replaces a file). ``github_commit_files`` publishes many workspace
files as ONE commit (``sensitive``). Both run on the server with the owner's token: the
token never enters the sandbox."""

from __future__ import annotations

import asyncio
import base64
import os
import stat
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.integrations import github as gh
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
from app.workspaces.archive import ArchiveError, unpack_repository
from app.workspaces.paths import normalise, resolve

REPO = string_prop("Repository as owner/name", pattern=gh.REPO_RE.pattern)
REF = string_prop("Branch, tag or commit (default: the repository's default branch)", maxLength=200)
LIMIT = {"type": "integer", "minimum": 1, "maximum": 100}


async def _access(ctx: ToolContext) -> gh.GitHubAccess:
    async with ctx.sessionmaker() as db:
        access = await gh.access_for(db, ctx.settings, ctx.user_id)
    if access is None:
        raise ToolFailed("GitHub is not connected (Integrations → GitHub).")
    return access


async def _call(ctx: ToolContext, method: str, path: str, **kw: Any) -> Any:
    access = await _access(ctx)
    try:
        return await gh.call(ctx.settings, access.token, method, path, **kw)
    except gh.GitHubError as exc:
        raise ToolFailed(str(exc)) from None


class GitHubTool(BaseTool):
    group = "github"

    async def available(self, db: AsyncSession, user_id: Any, settings: Settings) -> bool:
        return await gh.access_for(db, settings, user_id) is not None

    async def check_scope(self, ctx: ToolContext, args: dict[str, Any]) -> None:
        repo = args.get("repo")
        if repo is None:
            return
        if not gh.REPO_RE.match(repo):
            raise ScopeError("repository must be owner/name")
        access = await _access(ctx)
        if not access.repo_allowed(repo):
            raise ScopeError(f"{repo} is not in the allowed repositories")
        for key in ("branch", "head", "base"):
            if key in args and not gh.BRANCH_RE.match(args[key]):
                raise ScopeError(f"invalid branch name: {args[key]}")


class ListRepos(GitHubTool):
    name = "github_list_repos"
    title = "List GitHub repositories"
    description = "List repositories the GitHub token can access."
    category = ToolCategory.READ
    input_schema = object_schema({"limit": LIMIT}, [])

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        access = await _access(ctx)
        data = await _call(
            ctx, "GET", "/user/repos", params={"per_page": args.get("limit", 50), "sort": "pushed"}
        )
        rows = [r for r in data if access.repo_allowed(r["full_name"])]
        lines = [
            f"{r['full_name']} ({'private' if r.get('private') else 'public'}, "
            f"default branch {r.get('default_branch')})"
            for r in rows
        ]
        return ToolOutput("\n".join(lines) or "No repositories.")


class ListDir(GitHubTool):
    name = "github_list_dir"
    title = "List a GitHub folder"
    description = "List files in a folder of a repository."
    category = ToolCategory.READ
    input_schema = object_schema(
        {"repo": REPO, "path": string_prop("Folder path", default=""), "ref": REF}, ["repo"]
    )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        params = {"ref": args["ref"]} if args.get("ref") else None
        data = await _call(
            ctx,
            "GET",
            f"/repos/{args['repo']}/contents/{args.get('path', '').strip('/')}",
            params=params,
        )
        if isinstance(data, dict):
            return ToolOutput(f"{data.get('path')} is a file ({data.get('size')} bytes).")
        return ToolOutput(
            "\n".join(f"{i['path']}{'/' if i['type'] == 'dir' else ''}" for i in data) or "(empty)"
        )


class ReadFile(GitHubTool):
    name = "github_read_file"
    title = "Read a GitHub file"
    description = "Read a text file from a repository."
    category = ToolCategory.READ
    input_schema = object_schema(
        {"repo": REPO, "path": string_prop("File path"), "ref": REF}, ["repo", "path"]
    )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        params = {"ref": args["ref"]} if args.get("ref") else None
        data = await _call(
            ctx, "GET", f"/repos/{args['repo']}/contents/{args['path'].strip('/')}", params=params
        )
        if not isinstance(data, dict) or data.get("type") != "file":
            raise ToolFailed("Not a file.")
        if int(data.get("size") or 0) > ctx.settings.workspace_max_file_bytes:
            raise ToolFailed("The file is too large to read.")
        try:
            return ToolOutput(gh.decode_content(data))
        except gh.GitHubError as exc:
            raise ToolFailed(str(exc)) from None


class ListIssues(GitHubTool):
    name = "github_list_issues"
    title = "List GitHub issues"
    description = "List issues of a repository."
    category = ToolCategory.READ
    input_schema = object_schema(
        {
            "repo": REPO,
            "state": {"type": "string", "enum": ["open", "closed", "all"]},
            "limit": LIMIT,
        },
        ["repo"],
    )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        data = await _call(
            ctx,
            "GET",
            f"/repos/{args['repo']}/issues",
            params={"state": args.get("state", "open"), "per_page": args.get("limit", 30)},
        )
        lines = [
            f"#{i['number']} [{i['state']}] {i['title']}"
            + (" (pull request)" if "pull_request" in i else "")
            for i in data
        ]
        return ToolOutput("\n".join(lines) or "No issues.")


class GetIssue(GitHubTool):
    name = "github_get_issue"
    title = "Read a GitHub issue"
    description = "Read one issue with its comments."
    category = ToolCategory.READ
    input_schema = object_schema(
        {"repo": REPO, "number": {"type": "integer", "minimum": 1}}, ["repo", "number"]
    )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        issue = await _call(ctx, "GET", f"/repos/{args['repo']}/issues/{args['number']}")
        comments = await _call(
            ctx,
            "GET",
            f"/repos/{args['repo']}/issues/{args['number']}/comments",
            params={"per_page": 20},
        )
        parts = [
            f"#{issue['number']} {issue['title']} [{issue['state']}] by {issue['user']['login']}",
            issue.get("body") or "",
        ]
        parts += [f"--- {c['user']['login']}:\n{c.get('body') or ''}" for c in comments]
        return ToolOutput("\n\n".join(parts))


class ListCommits(GitHubTool):
    name = "github_list_commits"
    title = "GitHub history"
    description = "List recent commits of a branch (optionally for one path)."
    category = ToolCategory.READ
    input_schema = object_schema(
        {
            "repo": REPO,
            "ref": REF,
            "path": string_prop("Only commits touching this path"),
            "limit": LIMIT,
        },
        ["repo"],
    )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        params: dict[str, Any] = {"per_page": args.get("limit", 20)}
        if args.get("ref"):
            params["sha"] = args["ref"]
        if args.get("path"):
            params["path"] = args["path"]
        data = await _call(ctx, "GET", f"/repos/{args['repo']}/commits", params=params)
        lines = [
            f"{c['sha'][:10]} {c['commit']['author']['date'][:10]} "
            f"{c['commit']['message'].splitlines()[0][:120]}"
            for c in data
        ]
        return ToolOutput("\n".join(lines) or "No commits.")


class CreateBranch(GitHubTool):
    name = "github_create_branch"
    title = "Create a GitHub branch"
    description = "Create a new branch from another branch (default: the default branch)."
    category = ToolCategory.WRITE
    input_schema = object_schema(
        {"repo": REPO, "branch": string_prop("New branch name"), "from_ref": REF},
        ["repo", "branch"],
    )

    def describe(self, args: dict[str, Any]) -> OperationInfo:
        return OperationInfo(
            summary=f"Create branch {args['branch']} in {args['repo']}",
            resources=[f"github:{args['repo']}"],
            consequences="A new branch appears in the repository. Nothing else changes.",
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        repo = args["repo"]
        base = args.get("from_ref") or await self._default(ctx, repo)
        ref = await _call(ctx, "GET", f"/repos/{repo}/git/ref/heads/{base}")
        await _call(
            ctx,
            "POST",
            f"/repos/{repo}/git/refs",
            json={"ref": f"refs/heads/{args['branch']}", "sha": ref["object"]["sha"]},
        )
        return ToolOutput(f"Created branch {args['branch']} from {base}.")

    async def _default(self, ctx: ToolContext, repo: str) -> str:
        data = await _call(ctx, "GET", f"/repos/{repo}")
        return str(data.get("default_branch") or "main")


class WriteFile(CreateBranch):
    name = "github_write_file"
    title = "Commit a file to GitHub"
    description = (
        "Create or update one file on a branch as a commit. "
        "Committing to the default branch needs approval."
    )
    category = ToolCategory.WRITE
    input_schema = object_schema(
        {
            "repo": REPO,
            "branch": string_prop("Branch to commit to"),
            "path": string_prop("File path"),
            "content": {"type": "string"},
            "message": string_prop("Commit message", maxLength=500),
        },
        ["repo", "branch", "path", "content", "message"],
    )

    async def category_for(self, ctx: ToolContext, args: dict[str, Any]) -> ToolCategory:
        default = await self._default(ctx, args["repo"])
        return ToolCategory.SENSITIVE if args["branch"] == default else ToolCategory.WRITE

    def describe(self, args: dict[str, Any]) -> OperationInfo:
        return OperationInfo(
            summary=f"Commit {args['path']} to {args['repo']}@{args['branch']}: "
            f"{args['message'][:120]}",
            resources=[f"github:{args['repo']}/{args['path']}@{args['branch']}"],
            consequences="A commit is pushed to this branch (visible to everyone with access).",
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        repo, path = args["repo"], args["path"].strip("/")
        sha = None
        try:
            existing = await _call(
                ctx, "GET", f"/repos/{repo}/contents/{path}", params={"ref": args["branch"]}
            )
            sha = existing.get("sha") if isinstance(existing, dict) else None
        except ToolFailed:
            sha = None  # new file
        body: dict[str, Any] = {
            "message": args["message"],
            "content": base64.b64encode(args["content"].encode()).decode(),
            "branch": args["branch"],
        }
        if sha:
            body["sha"] = sha
        data = await _call(ctx, "PUT", f"/repos/{repo}/contents/{path}", json=body)
        return ToolOutput(f"Committed {path} to {args['branch']} ({data['commit']['sha'][:10]}).")


class CreatePullRequest(GitHubTool):
    name = "github_create_pull_request"
    title = "Open a pull request"
    description = (
        "Open a pull request. Publishing: needs the owner's approval "
        "(unless the owner gave this agent full access)."
    )
    category = ToolCategory.SENSITIVE
    input_schema = object_schema(
        {
            "repo": REPO,
            "head": string_prop("Branch with the changes"),
            "base": string_prop("Target branch"),
            "title": string_prop("Title", maxLength=200),
            "body": {"type": "string", "maxLength": 20000},
        },
        ["repo", "head", "base", "title"],
    )

    def describe(self, args: dict[str, Any]) -> OperationInfo:
        return OperationInfo(
            summary=f"Open pull request in {args['repo']}: {args['head']} → {args['base']} — "
            f"{args['title']}",
            resources=[f"github:{args['repo']}"],
            consequences="A pull request is published under your GitHub account; "
            "people watching the repository are notified.",
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        data = await _call(
            ctx,
            "POST",
            f"/repos/{args['repo']}/pulls",
            json={
                "head": args["head"],
                "base": args["base"],
                "title": args["title"],
                "body": args.get("body", ""),
            },
        )
        return ToolOutput(f"Opened pull request #{data['number']}: {data['html_url']}")


async def _workspace_root(ctx: ToolContext) -> Path:
    return workspace_dir(ctx.settings, (await ctx.workspace()).id)


def _untracked(settings: Settings, path: str) -> bool:
    skip = set(settings.workspace_untracked_dirs)
    return any(part in skip for part in PurePosixPath(path).parts[:-1])


async def _record(ctx: ToolContext, changed: list[str]) -> None:
    ws = await ctx.workspace()
    async with ctx.sessionmaker() as db:
        await record_changes(
            db,
            ctx.settings,
            workspace=ws,
            changed=changed,
            deleted=[],
            task_id=ctx.task_id,
            agent_id=ctx.agent.id,
            tool_call_id=ctx.tool_call_id,
        )
        await db.commit()


def _repo_folder(args: dict[str, Any]) -> str:
    """The workspace folder that holds the repository (default: the repository name).
    A leading "/" is kept, so an absolute path is refused, not silently made relative."""
    folder = str(args.get("folder") or "").strip().rstrip("/")
    return folder or args["repo"].split("/")[-1]


def _has_files(path: Path) -> bool:
    return path.is_dir() and any(path.iterdir())


class Checkout(GitHubTool):
    name = "github_checkout"
    title = "Download a repository"
    description = (
        "Download a whole repository (a branch, tag or commit) into a folder of your "
        "workspace in one step, instead of reading files one by one. Then read and change "
        "it with the fs_* tools, run checks with terminal_run (for example `npm --prefix "
        '<folder> ci` with network "packages", then `npm --prefix <folder> run lint`), and '
        "publish your changes with github_commit_files (same folder). The folder must be "
        "new or empty, unless overwrite is true: then the repository's files replace "
        "files with the same path, and other files (node_modules, your new files) stay."
    )
    category = ToolCategory.WRITE
    input_schema = object_schema(
        {
            "repo": REPO,
            "ref": REF,
            "folder": string_prop(
                "Workspace folder to put it in (default: the repository name)", maxLength=200
            ),
            "overwrite": {
                "type": "boolean",
                "description": "Replace files in a folder that is not empty",
            },
        },
        ["repo"],
    )

    def timeout_for(self, settings: Settings) -> float:
        return settings.github_transfer_timeout_seconds

    async def check_scope(self, ctx: ToolContext, args: dict[str, Any]) -> None:
        await super().check_scope(ctx, args)
        if args.get("ref") and not gh.BRANCH_RE.match(args["ref"]):
            raise ScopeError(f"invalid branch, tag or commit: {args['ref']}")
        root = await _workspace_root(ctx)
        if resolve(root, _repo_folder(args)) == root:
            raise ScopeError("choose a folder inside the workspace, not the workspace itself")

    async def category_for(self, ctx: ToolContext, args: dict[str, Any]) -> ToolCategory:
        dest = resolve(await _workspace_root(ctx), _repo_folder(args))
        replaces = args.get("overwrite") and await asyncio.to_thread(_has_files, dest)
        return ToolCategory.SENSITIVE if replaces else ToolCategory.WRITE

    def describe(self, args: dict[str, Any]) -> OperationInfo:
        folder = _repo_folder(args)
        ref = args.get("ref") or "the default branch"
        return OperationInfo(
            summary=f"Download {args['repo']} ({ref}) into the workspace folder {folder}/",
            resources=[f"github:{args['repo']}", f"workspace:{folder}/"],
            consequences=(
                "The repository's files are written into this folder; files there with "
                "the same path are replaced. Nothing changes on GitHub."
                if args.get("overwrite")
                else "The repository's files are written into this new folder. "
                "Nothing changes on GitHub."
            ),
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        access = await _access(ctx)
        repo, folder = args["repo"], _repo_folder(args)
        root = await _workspace_root(ctx)
        dest = resolve(root, folder)
        if dest.exists() and not dest.is_dir():
            raise ToolFailed(f"{folder} is a file, not a folder.")
        if not args.get("overwrite") and await asyncio.to_thread(_has_files, dest):
            raise ToolFailed(
                f"The folder {folder}/ is not empty: set overwrite to replace the files in "
                "it with the repository's, or choose another folder."
            )
        settings = ctx.settings
        try:
            ref = args.get("ref") or await gh.default_branch(settings, access.token, repo)
            # Downloaded next to the workspaces, never into one (the sandbox cannot see it).
            with tempfile.TemporaryDirectory(dir=settings.workspace_root, prefix=".gh-") as tmp:
                archive = Path(tmp) / "repo.tar.gz"
                await gh.download_archive(
                    settings, access.token, repo, ref, archive, settings.github_checkout_max_bytes
                )
                result = await asyncio.to_thread(
                    unpack_repository,
                    archive,
                    root,
                    folder,
                    max_files=settings.github_checkout_max_files,
                    max_bytes=settings.github_checkout_max_bytes,
                )
        except (gh.GitHubError, ArchiveError) as exc:
            raise ToolFailed(str(exc)) from None
        tracked = [p for p in result.files if not _untracked(settings, p)]
        if tracked:
            await _record(ctx, tracked)
        commit = f", commit {result.commit[:10]}" if result.commit else ""
        lines = [
            f"Downloaded {repo} ({ref}{commit}) into {folder}/: {len(result.files)} files, "
            f"{result.total_bytes} bytes."
        ]
        if result.skipped:
            lines.append(
                f"Skipped {result.skipped} symbolic link(s) or special file(s): they are not "
                "unpacked."
            )
        lines.append(
            f"Run commands in it with terminal_run (e.g. `npm --prefix {folder} ci` with "
            f'network "packages"); publish changes with github_commit_files, folder "{folder}".'
        )
        return ToolOutput("\n".join(lines))


def _repo_path(path: str) -> str:
    """A repository path from the model: relative, no ``..``, nothing inside ``.git``."""
    clean = str(normalise(path))
    if clean == "." or ".git" in PurePosixPath(clean).parts:
        raise ScopeError(f"not a file path in the repository: {path}")
    return clean


def _commit_lists(args: dict[str, Any]) -> tuple[list[str], list[str]]:
    paths = [_repo_path(p) for p in args.get("paths") or []]
    deletes = [_repo_path(p) for p in args.get("delete") or []]
    if not paths and not deletes:
        raise ScopeError("give the files to commit (paths) or to delete (delete)")
    both = set(paths) & set(deletes)
    if both:
        raise ScopeError(f"a path cannot be both committed and deleted: {sorted(both)[0]}")
    return list(dict.fromkeys(paths)), list(dict.fromkeys(deletes))


def _read_for_commit(
    root: Path, folder: str, paths: list[str], max_bytes: int
) -> list[tuple[str, bytes, str]]:
    """(repository path, content, git mode) of each file — regular files only, no links."""
    out: list[tuple[str, bytes, str]] = []
    total = 0
    for rel in paths:
        full = resolve(root, f"{folder}/{rel}", must_exist=True)
        st = os.lstat(full)
        if not stat.S_ISREG(st.st_mode):
            raise ScopeError(f"{rel} is not a file")
        total += st.st_size
        if total > max_bytes:
            raise ToolFailed(
                f"The files are larger than {max_bytes} bytes in all (GITHUB_COMMIT_MAX_BYTES)."
            )
        out.append((rel, full.read_bytes(), "100755" if st.st_mode & 0o111 else "100644"))
    return out


def _as_text(data: bytes) -> str | None:
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


class CommitFiles(GitHubTool):
    name = "github_commit_files"
    title = "Commit files to GitHub"
    description = (
        "Publish several files from your workspace to a branch as ONE commit (instead of "
        "one commit per file). The branch is created from base (default: the repository's "
        "default branch) if it does not exist. folder: the workspace folder holding the "
        'repository (default: the repository name, as github_checkout uses; "." = the '
        "workspace itself). paths: the new or changed files, relative to that folder — "
        "the same paths as in the repository. delete: repository paths to remove. Needs "
        "the owner's approval (unless the owner gave this agent full access); open a pull "
        "request afterwards with github_create_pull_request."
    )
    category = ToolCategory.SENSITIVE
    input_schema = object_schema(
        {
            "repo": REPO,
            "branch": string_prop("Branch to commit to (created if it does not exist)"),
            "base": string_prop("Branch to create it from (default: the default branch)"),
            "message": string_prop("Commit message", minLength=1, maxLength=5000),
            "folder": string_prop("Workspace folder that holds the repository", maxLength=200),
            "paths": {
                "type": "array",
                "items": {"type": "string", "maxLength": 512},
                "maxItems": 5000,
                "description": "Files to add or update, relative to folder",
            },
            "delete": {
                "type": "array",
                "items": {"type": "string", "maxLength": 512},
                "maxItems": 5000,
                "description": "Repository paths to delete",
            },
        },
        ["repo", "branch", "message"],
    )

    def timeout_for(self, settings: Settings) -> float:
        return settings.github_transfer_timeout_seconds

    async def check_scope(self, ctx: ToolContext, args: dict[str, Any]) -> None:
        await super().check_scope(ctx, args)
        paths, deletes = _commit_lists(args)
        limit = ctx.settings.github_commit_max_files
        if len(paths) + len(deletes) > limit:
            raise ScopeError(f"more than {limit} files in one commit (GITHUB_COMMIT_MAX_FILES)")
        root, folder = await _workspace_root(ctx), _repo_folder(args)
        resolve(root, folder)
        for rel in paths:
            full = resolve(root, f"{folder}/{rel}", must_exist=True)
            if not full.is_file():
                raise ScopeError(f"{rel} is not a file")

    def describe(self, args: dict[str, Any]) -> OperationInfo:
        repo, branch = args["repo"], args["branch"]
        paths = list(dict.fromkeys(args.get("paths") or []))
        deletes = list(dict.fromkeys(args.get("delete") or []))
        what = f"{len(paths)} file(s)" + (f", delete {len(deletes)}" if deletes else "")
        listed = [*paths, *(f"delete: {p}" for p in deletes)]
        shown = listed[:18] + ([f"… and {len(listed) - 18} more"] if len(listed) > 18 else [])
        base = args.get("base") or "the default branch"
        return OperationInfo(
            summary=f"Commit {what} to {repo}@{branch}: {args['message'][:120]}",
            resources=[f"github:{repo}@{branch}", *shown],
            consequences=(
                f"One commit with these files is pushed to {branch} (created from {base} if "
                "it does not exist). It is visible to everyone with access to the repository."
            ),
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        access = await _access(ctx)
        settings, token = ctx.settings, access.token
        repo, branch = args["repo"], args["branch"]
        paths, deletes = _commit_lists(args)
        root, folder = await _workspace_root(ctx), _repo_folder(args)
        files = await asyncio.to_thread(
            _read_for_commit, root, folder, paths, settings.github_commit_max_bytes
        )

        async def api(method: str, path: str, **kw: Any) -> Any:
            return await gh.call(settings, token, method, f"/repos/{repo}{path}", **kw)

        try:
            head = await api("GET", f"/git/ref/heads/{branch}", missing_ok=True)
            created_from = None
            if head is None:  # a new branch, from base
                created_from = args.get("base") or await gh.default_branch(settings, token, repo)
                head = await api("GET", f"/git/ref/heads/{created_from}")
            parent = head["object"]["sha"]
            base_tree = (await api("GET", f"/git/commits/{parent}"))["tree"]["sha"]
            entries: list[dict[str, Any]] = []
            for rel, data, mode in files:
                text = _as_text(data)
                if text is not None:  # GitHub stores inline text as a blob itself
                    entries.append({"path": rel, "mode": mode, "type": "blob", "content": text})
                    continue
                blob = await api(
                    "POST",
                    "/git/blobs",
                    json={"content": base64.b64encode(data).decode(), "encoding": "base64"},
                )
                entries.append({"path": rel, "mode": mode, "type": "blob", "sha": blob["sha"]})
            entries += [{"path": p, "mode": "100644", "type": "blob", "sha": None} for p in deletes]
            tree = await api("POST", "/git/trees", json={"base_tree": base_tree, "tree": entries})
            if tree["sha"] == base_tree:
                where = f"{created_from}, so {branch} was not created" if created_from else branch
                return ToolOutput(f"Nothing to commit: these files are already so on {where}.")
            commit = await api(
                "POST",
                "/git/commits",
                json={"message": args["message"], "tree": tree["sha"], "parents": [parent]},
            )
            if created_from:
                await api(
                    "POST", "/git/refs", json={"ref": f"refs/heads/{branch}", "sha": commit["sha"]}
                )
            else:  # fast-forward only: a branch that moved meanwhile is not overwritten
                await api(
                    "PATCH",
                    f"/git/refs/heads/{branch}",
                    json={"sha": commit["sha"], "force": False},
                )
        except gh.GitHubError as exc:
            raise ToolFailed(str(exc)) from None
        made = f" (new branch from {created_from})" if created_from else ""
        gone = f", deleted {len(deletes)}" if deletes else ""
        link = f" {commit['html_url']}" if commit.get("html_url") else ""
        return ToolOutput(
            f"Committed {len(files)} file(s){gone} to {repo}@{branch}{made} as one commit "
            f"{str(commit['sha'])[:10]}.{link}"
        )


GITHUB_TOOLS: tuple[BaseTool, ...] = (
    ListRepos(),
    ListDir(),
    ReadFile(),
    ListIssues(),
    GetIssue(),
    ListCommits(),
    Checkout(),
    CreateBranch(),
    WriteFile(),
    CommitFiles(),
    CreatePullRequest(),
)
