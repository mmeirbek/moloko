"""GitHub tools (spec 15.6). Reading is ``read``; creating a branch or committing to a
non-default branch is ``write``; committing to the default branch and opening a pull
request (publishing) are ``sensitive``."""

from __future__ import annotations

import base64
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.integrations import github as gh
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
    description = "Open a pull request. Publishing: always needs the owner's approval."
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


GITHUB_TOOLS: tuple[BaseTool, ...] = (
    ListRepos(),
    ListDir(),
    ReadFile(),
    ListIssues(),
    GetIssue(),
    ListCommits(),
    CreateBranch(),
    WriteFile(),
    CreatePullRequest(),
)
