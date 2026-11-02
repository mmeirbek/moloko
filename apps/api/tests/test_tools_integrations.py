"""Terminal (sandbox), web (SSRF), GitHub, MCP and the owner-facing APIs (spec 15, 16)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from mcp import Client
from mcp.server.mcpserver import MCPServer
from pydantic import SecretStr
from sqlalchemy import select

from app.integrations import github as gh
from app.models import Integration
from app.providers import mock_provider
from app.sandbox.base import SandboxResult, SandboxUnavailable
from app.services.users import UserService
from app.tools import mcp as mcp_module
from app.tools.base import ScopeError
from app.tools.builtin import web
from app.tools.builtin.terminal import parse_command
from tests.conftest import (
    OWNER_PASSWORD,
    OWNER_USERNAME,
    AppFactory,
    RecordingQueue,
    csrf_headers,
    drain,
    logged_in_client,
    make_settings,
    run_agent,
)
from tests.tools_helpers import audit_actions, scripted, tool_agent, tool_calls


class FakeSandbox:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[list[str]] = []

    async def run(
        self, workspace_id: uuid.UUID, argv: list[str], *, timeout_seconds: int
    ) -> SandboxResult:
        self.calls.append(argv)
        (self.root / str(workspace_id) / "out.txt").write_text("result")
        return SandboxResult(exit_code=0, stdout="hello\n", stderr="")

    async def health(self) -> dict[str, object]:
        return {"ok": True, "image": "img", "limits": {"cpus": 1}, "network": "none"}


@pytest.fixture
async def tool_app(app_factory: AppFactory, tmp_path: Path) -> FastAPI:
    app = await app_factory(workspace_root=str(tmp_path / "ws"), app_encryption_key="k" * 44)
    async with app.state.db.sessionmaker() as db:
        await UserService(db).create_owner(OWNER_USERNAME, OWNER_PASSWORD, "Owner")
    app.state.queue = RecordingQueue()
    return app


# --- terminal ------------------------------------------------------------------------------


def test_commands_run_without_a_shell_and_only_from_the_allow_list() -> None:
    allowed = ["python", "ls"]
    assert parse_command("python main.py --x 'a b'", allowed) == ["python", "main.py", "--x", "a b"]
    for bad in ("rm -rf /", "/usr/bin/python x", "", "python 'unclosed"):
        with pytest.raises(ScopeError):
            parse_command(bad, allowed)
    # Shell syntax is just text for the program, never interpreted.
    assert parse_command("ls ; rm -rf /", allowed) == ["ls", ";", "rm", "-rf", "/"]


async def test_terminal_runs_in_the_sandbox_and_records_changed_files(
    tool_app: FastAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.workers import jobs

    sandbox = FakeSandbox(tmp_path / "ws")
    monkeypatch.setattr(jobs, "make_sandbox", lambda settings: sandbox)
    monkeypatch.setattr(tool_app.state.settings, "sandbox_url", "http://sandbox:8090")
    monkeypatch.setattr(tool_app.state.settings, "sandbox_runner_token", SecretStr("t" * 32))
    monkeypatch.setattr(
        mock_provider,
        "_handlers",
        [scripted(("terminal_run", {"command": "python main.py"}), "ran")],
    )
    async with logged_in_client(tool_app) as client:
        agent = await tool_agent(client, tools=["terminal_run"])
        task_id = (await run_agent(client, agent["id"], "Run it")).json()["task"]["id"]
        await drain(tool_app, tool_app.state.queue)
    assert sandbox.calls == [["python", "main.py"]]
    call = (await tool_calls(tool_app, task_id))[0]
    assert (
        call.status == "succeeded"
        and "exit code 0" in (call.result or "")
        and "hello" in (call.result or "")
    )
    changed = await audit_actions(tool_app, "workspace.files_changed")
    assert changed[0].details["changed"] == ["out.txt"]


# --- web: SSRF guard ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "addr"),
    [
        ("http://localhost/", "127.0.0.1"),
        ("http://internal.example/", "10.0.0.5"),
        ("http://metadata.example/latest", "169.254.169.254"),
        ("http://v6.example/", "::1"),
        ("http://mapped.example/", "::ffff:192.168.1.1"),
        ("http://postgres/", "172.20.0.2"),
    ],
)
async def test_web_fetch_refuses_private_addresses(
    url: str, addr: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def resolve(host: str, port: int) -> list[str]:
        return [addr]

    monkeypatch.setattr(web, "RESOLVE", resolve)
    with pytest.raises(ScopeError):
        await web.check_url(url, make_settings())


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/",
        "http://user:pw@example.com/",
        "http://example.com:22/",
        "file:///etc/passwd",
    ],
)
async def test_web_fetch_refuses_bad_urls(url: str) -> None:
    with pytest.raises(ScopeError):
        await web.check_url(url, make_settings())


async def test_web_fetch_pins_the_checked_address_and_rechecks_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    addrs = {"example.com": "93.184.216.34", "evil.example": "127.0.0.1"}
    seen: list[httpx2.Request] = []

    async def resolve(host: str, port: int) -> list[str]:
        return [addrs[host]]

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if request.url.path == "/go":
            return httpx2.Response(302, headers={"location": "http://evil.example/admin"})
        html = (
            "<html><head><title>Hi</title><script>x()</script></head>"
            "<body><p>Hello <b>world</b></p></body></html>"
        )
        return httpx2.Response(200, headers={"content-type": "text/html"}, text=html)

    monkeypatch.setattr(web, "RESOLVE", resolve)
    monkeypatch.setattr(web, "TRANSPORT", httpx2.MockTransport(handler))
    _, _, body = await web.fetch("https://example.com/page", make_settings())
    assert seen[0].url.host == "93.184.216.34" and seen[0].headers["host"] == "example.com"
    assert seen[0].extensions["sni_hostname"] == "example.com"
    assert web.html_to_text(body) == ("Hi", "Hello world")
    with pytest.raises(ScopeError):
        await web.fetch("https://example.com/go", make_settings())  # redirect to a private address


# --- GitHub --------------------------------------------------------------------------------------


def github_mock(log: list[httpx2.Request]) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        log.append(request)
        path = request.url.path
        if path == "/user":
            return httpx2.Response(200, json={"login": "owner"})
        if path == "/repos/me/app":
            return httpx2.Response(200, json={"default_branch": "main"})
        if path.startswith("/repos/me/app/contents/") and request.method == "GET":
            return httpx2.Response(404, json={"message": "Not Found"})
        if path.startswith("/repos/me/app/contents/") and request.method == "PUT":
            return httpx2.Response(201, json={"commit": {"sha": "abcdef1234567890"}})
        return httpx2.Response(404, json={})

    return httpx2.MockTransport(handler)


async def test_github_token_is_encrypted_and_never_shown(
    tool_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    log: list[httpx2.Request] = []
    monkeypatch.setattr(gh, "TRANSPORT", github_mock(log))
    token = "github_pat_" + "x" * 40
    async with logged_in_client(tool_app) as client:
        resp = await client.put(
            "/api/v1/integrations/github",
            json={"token": token, "allowed_repos": ["me/app"]},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        status = (await client.get("/api/v1/integrations/status")).json()
    assert body["connected"] and body["login"] == "owner" and body["token_hint"] == "…" + token[-4:]
    assert token not in json.dumps(body) and token not in json.dumps(status)
    assert (
        log[0].headers["authorization"] == f"Bearer {token}" and log[0].url.host == "api.github.com"
    )
    async with tool_app.state.db.sessionmaker() as db:
        row = (await db.execute(select(Integration))).scalar_one()
    assert row.secret_encrypted and token not in row.secret_encrypted
    assert all(token not in json.dumps(a.details) for a in await audit_actions(tool_app, ""))


async def test_github_commit_to_the_default_branch_is_sensitive(
    tool_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gh, "TRANSPORT", github_mock([]))
    monkeypatch.setattr(
        mock_provider,
        "_handlers",
        [
            scripted(
                (
                    "github_write_file",
                    {
                        "repo": "me/app",
                        "branch": "feature",
                        "path": "a.md",
                        "content": "x",
                        "message": "m",
                    },
                ),
                (
                    "github_write_file",
                    {
                        "repo": "me/app",
                        "branch": "main",
                        "path": "a.md",
                        "content": "x",
                        "message": "m",
                    },
                ),
                "ok",
            )
        ],
    )
    async with logged_in_client(tool_app) as client:
        await client.put(
            "/api/v1/integrations/github",
            json={"token": "github_pat_" + "y" * 40, "allowed_repos": ["me/app"]},
            headers=await csrf_headers(client),
        )
        agent = await tool_agent(client, autonomy="balanced", tools=["github_write_file"])
        task_id = (await run_agent(client, agent["id"], "Commit")).json()["task"]["id"]
        await drain(tool_app, tool_app.state.queue)
    calls = await tool_calls(tool_app, task_id)
    assert (calls[0].category, calls[0].status) == ("write", "succeeded")
    assert (calls[1].category, calls[1].status) == ("sensitive", "awaiting_approval")


async def test_github_repositories_outside_the_allow_list_are_refused(
    tool_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gh, "TRANSPORT", github_mock([]))
    monkeypatch.setattr(
        mock_provider,
        "_handlers",
        [scripted(("github_read_file", {"repo": "other/repo", "path": "x"}), "ok")],
    )
    async with logged_in_client(tool_app) as client:
        await client.put(
            "/api/v1/integrations/github",
            json={"token": "github_pat_" + "z" * 40, "allowed_repos": ["me/app"]},
            headers=await csrf_headers(client),
        )
        agent = await tool_agent(client, tools=["github_read_file"])
        task_id = (await run_agent(client, agent["id"], "Read")).json()["task"]["id"]
        await drain(tool_app, tool_app.state.queue)
    call = (await tool_calls(tool_app, task_id))[0]
    assert call.status == "denied" and "allowed repositories" in (call.decision_reason or "")


# --- MCP -----------------------------------------------------------------------------


def demo_server(up: dict[str, bool]) -> MCPServer:
    server = MCPServer("demo")

    @server.tool(description="Add two numbers")
    def add(a: int, b: int) -> str:
        return str(a + b)

    @server.tool(description="Delete everything")
    def nuke() -> str:
        return "boom"

    def factory(row: Any, token: str | None, settings: Any) -> Client:
        if not up["value"]:
            raise ConnectionError("down")
        return Client(server)

    mcp_module.CLIENT_FACTORY = factory
    return server


async def test_mcp_tools_start_disabled_and_are_permission_checked(
    tool_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    up = {"value": True}
    monkeypatch.setattr(mcp_module, "CLIENT_FACTORY", mcp_module.CLIENT_FACTORY)
    demo_server(up)
    monkeypatch.setattr(
        mock_provider,
        "_handlers",
        [
            scripted(
                ("mcp_demo_add", {"a": 2, "b": 3}), ("mcp_demo_add", {"a": 1, "b": 1}), "sum done"
            )
        ],
    )
    async with logged_in_client(tool_app) as client:
        resp = await client.post(
            "/api/v1/mcp-servers",
            json={"name": "Demo", "url": "http://mcp.local/mcp"},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 201, resp.text
        server = resp.json()
        assert server["status"] == "ok"
        tools = {t["name"]: t for t in server["tools"]}
        assert set(tools) == {"mcp_demo_add", "mcp_demo_nuke"}
        assert all(
            not t["enabled"] and t["category"] == "sensitive" for t in tools.values()
        )  # never auto-trusted

        agent = await tool_agent(client, tools=["mcp_demo_add"])
        task_id = (await run_agent(client, agent["id"], "Add")).json()["task"]["id"]
        await drain(tool_app, tool_app.state.queue)
        first = (await tool_calls(tool_app, task_id))[0]
        assert first.status == "denied" and "turned off" in (first.decision_reason or "")

        resp = await client.patch(
            "/api/v1/tools/mcp_demo_add",
            json={"enabled": True, "category": "read"},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 200 and resp.json()["enabled"]
        task_id = (await run_agent(client, agent["id"], "Add again")).json()["task"]["id"]
        up["value"] = True
        await drain(tool_app, tool_app.state.queue)
        ok = (await tool_calls(tool_app, task_id))[0]
        assert ok.status == "succeeded" and "5" in (ok.result or "")

        up["value"] = False  # the server goes down: the call fails, nothing crashes
        task_id = (await run_agent(client, agent["id"], "Add while down")).json()["task"]["id"]
        await drain(tool_app, tool_app.state.queue)
        down = (await tool_calls(tool_app, task_id))[0]
        assert down.status == "failed" and "unavailable" in (down.result or "")
        refreshed = (
            await client.post(
                f"/api/v1/mcp-servers/{server['id']}/refresh", headers=await csrf_headers(client)
            )
        ).json()
        assert refreshed["status"] == "error"


async def test_built_in_tools_can_be_turned_off(tool_app: FastAPI) -> None:
    async with logged_in_client(tool_app) as client:
        tools = {t["name"]: t for t in (await client.get("/api/v1/tools")).json()}
        assert tools["fs_read"]["enabled"] and tools["fs_delete"]["category"] == "sensitive"
        assert not tools["terminal_run"]["available"]  # no sandbox configured
        assert not tools["github_read_file"]["available"]  # GitHub not connected
        resp = await client.patch(
            "/api/v1/tools/fs_read", json={"enabled": False}, headers=await csrf_headers(client)
        )
        assert resp.json()["enabled"] is False
        resp = await client.patch(
            "/api/v1/tools/fs_read", json={"category": "read"}, headers=await csrf_headers(client)
        )
        assert resp.status_code == 422
        bad = await client.post(
            "/api/v1/agents",
            json={"name": "X", "allowed_tools": ["rm_rf"]},
            headers=await csrf_headers(client),
        )
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "unknown_tool"


async def test_audit_log_api_pages_and_filters(
    tool_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mock_provider, "_handlers", [scripted(("fs_list", {}), "ok")])
    async with logged_in_client(tool_app) as client:
        agent = await tool_agent(client, tools=["fs_list"])
        await run_agent(client, agent["id"], "List")
        await drain(tool_app, tool_app.state.queue)
        page = (await client.get("/api/v1/audit?limit=2")).json()
        assert len(page["items"]) == 2 and page["next_cursor"]
        rest = (await client.get(f"/api/v1/audit?limit=200&cursor={page['next_cursor']}")).json()
        ids = [i["id"] for i in page["items"]] + [i["id"] for i in rest["items"]]
        assert len(ids) == len(set(ids))
        tools_only = (await client.get("/api/v1/audit?action=tool.")).json()["items"]
        assert {i["action"] for i in tools_only} == {"tool.authorized", "tool.executed"}
        assert all(
            i["action"] == "auth.login"
            for i in (await client.get("/api/v1/audit?action=auth.login")).json()["items"]
        )


async def test_sandbox_unavailable_is_reported_not_crashed() -> None:
    from app.sandbox.client import RunnerSandbox

    settings = make_settings(sandbox_url="http://127.0.0.1:1", sandbox_runner_token="t" * 32)
    with pytest.raises(SandboxUnavailable):
        await RunnerSandbox(settings).run(uuid.uuid4(), ["ls"], timeout_seconds=1)
    assert (await RunnerSandbox(settings).health()) == {"ok": False}


async def test_official_github_mcp_server_uses_the_saved_token(
    tool_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mcp_types import ToolAnnotations

    seen: dict[str, Any] = {}
    server = MCPServer("github")

    @server.tool(description="Get a file", annotations=ToolAnnotations(read_only_hint=True))
    def get_file_contents(owner: str, repo: str, path: str) -> str:
        return f"{owner}/{repo}/{path}"

    @server.tool(description="Create a PR")
    def create_pull_request(owner: str, repo: str, title: str) -> str:
        return "PR"

    def factory(row: Any, token: str | None, settings: Any) -> Client:
        seen.update(url=row.url, token=token, headers=dict(row.headers))
        return Client(server)

    monkeypatch.setattr(mcp_module, "CLIENT_FACTORY", factory)
    monkeypatch.setattr(gh, "TRANSPORT", github_mock([]))
    pat = "github_pat_" + "m" * 40
    async with logged_in_client(tool_app) as client:
        early = await client.post(
            "/api/v1/mcp-servers/github", json={}, headers=await csrf_headers(client)
        )
        assert early.status_code == 409 and early.json()["error"]["code"] == "github_not_connected"
        await client.put(
            "/api/v1/integrations/github", json={"token": pat}, headers=await csrf_headers(client)
        )
        resp = await client.post(
            "/api/v1/mcp-servers/github",
            json={"readonly": True, "toolsets": ["repos", "pull_requests"]},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
    assert body["auth_source"] == "github" and body["has_token"] is False  # no second copy
    assert seen["token"] == pat and seen["url"] == "https://api.githubcopilot.com/mcp/"
    assert seen["headers"] == {"X-MCP-Readonly": "true", "X-MCP-Toolsets": "repos,pull_requests"}
    tools = {t["name"]: t for t in body["tools"]}
    assert all(not t["enabled"] for t in tools.values())  # never auto-trusted
    assert tools["mcp_github_get_file_contents"]["category"] == "read"  # from the read-only hint
    assert tools["mcp_github_create_pull_request"]["category"] == "sensitive"
    assert pat not in json.dumps(body)
