"""The agents' browser: egress proxy (SSRF), container spec, tool with approval, export."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from app.providers import mock_provider
from app.sandbox.base import SandboxResult
from app.sandbox.egress import EgressProxy, serve
from app.sandbox.runner import BrowseRequest, RunnerSettings, browser_spec
from app.services.users import UserService
from app.tools.builtin import web
from app.tools.builtin.browser import screenshot_name
from tests.conftest import (
    OWNER_PASSWORD,
    OWNER_USERNAME,
    AppFactory,
    RecordingQueue,
    drain,
    logged_in_client,
    run_agent,
)
from tests.tools_helpers import approvals, decide, scripted, tool_agent, tool_calls

# --- egress proxy -----------------------------------------------------------------------------


async def _origin(handler_text: bytes) -> tuple[asyncio.Server, int]:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read(65_536)
        writer.write(handler_text)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def _ask(proxy_port: int, request: bytes) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
    writer.write(request)
    await writer.drain()
    data = await asyncio.wait_for(reader.read(65_536), 5)
    writer.close()
    return data


async def test_egress_refuses_private_addresses_and_odd_ports() -> None:
    origin, port = await _origin(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
    loopback = EgressProxy(
        allowed_ports=(port,), resolver=lambda h, p: asyncio.sleep(0, ["127.0.0.1"])
    )
    server = await serve(loopback, "127.0.0.1", 0)
    pport = server.sockets[0].getsockname()[1]
    try:
        refused = await _ask(
            pport, f"GET http://intranet.test:{port}/ HTTP/1.1\r\nHost: x\r\n\r\n".encode()
        )
        assert b"403" in refused.split(b"\r\n")[0] and b"private or local" in refused
        tunnel = await _ask(pport, f"CONNECT 10.0.0.5:{port} HTTP/1.1\r\n\r\n".encode())
        assert b"403" in tunnel.split(b"\r\n")[0]
        odd = await _ask(pport, b"CONNECT example.org:22 HTTP/1.1\r\n\r\n")
        assert b"403" in odd and b"port 22" in odd
    finally:
        server.close()
        origin.close()


async def test_egress_forwards_to_allowed_addresses() -> None:
    origin, port = await _origin(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello")
    proxy = EgressProxy(
        allowed_ports=(port,),
        resolver=lambda h, p: asyncio.sleep(0, ["127.0.0.1"]),
        allow_private=True,
    )
    server = await serve(proxy, "127.0.0.1", 0)
    pport = server.sockets[0].getsockname()[1]
    try:
        plain = await _ask(
            pport,
            f"GET http://site.test:{port}/a?b=1 HTTP/1.1\r\nHost: site.test\r\n"
            "Proxy-Connection: keep-alive\r\n\r\n".encode(),
        )
        assert plain.endswith(b"hello")
        reader, writer = await asyncio.open_connection("127.0.0.1", pport)
        writer.write(f"CONNECT site.test:{port} HTTP/1.1\r\n\r\n".encode())
        await writer.drain()
        assert b"200 Connection Established" in await reader.readuntil(b"\r\n\r\n")
        writer.write(b"GET / HTTP/1.1\r\n\r\n")
        await writer.drain()
        assert (await asyncio.wait_for(reader.read(65_536), 5)).endswith(b"hello")
        writer.close()
    finally:
        server.close()
        origin.close()


# --- container spec ---------------------------------------------------------------------------


def test_browser_container_is_locked_down_and_takes_the_url_as_an_argument() -> None:
    settings = RunnerSettings(sandbox_runner_token=SecretStr("t" * 32))
    url = "https://example.org/$(reboot)';rm -rf /"
    spec = browser_spec(
        settings,
        BrowseRequest(
            workspace_id=uuid.uuid4(),
            mode="page",
            url=url,
            screenshot="screenshots/example.org-1.png",
            dom=".browser/0123456789abcdef.html",
        ),
    )
    host = spec["HostConfig"]
    assert host["NetworkMode"] == "moloko_browser" and host["ReadonlyRootfs"] is True
    assert host["CapDrop"] == ["ALL"] and spec["User"] == "10001:10001"
    assert spec["Image"] == "moloko-browser:local"
    argv = spec["Cmd"]
    assert argv[:2] == ["sh", "-c"] and url not in argv[2] and argv[4] == url  # never in the script
    pdf = browser_spec(
        settings,
        BrowseRequest(
            workspace_id=uuid.uuid4(),
            mode="pdf",
            source=".browser/0123456789abcdef.html",
            pdf="exports/r.pdf",
        ),
    )
    assert pdf["HostConfig"]["NetworkMode"] == "none"  # printing needs no network
    for bad in ("../etc/passwd.png", "screenshots/../../x.png", "/workspace/x.png"):
        with pytest.raises(ValueError):
            browser_spec(
                settings,
                BrowseRequest(
                    workspace_id=uuid.uuid4(),
                    mode="page",
                    url="https://a.org",
                    screenshot=bad,
                    dom=".browser/abcdef0123.html",
                ),
            )


def test_screenshot_names_are_safe() -> None:
    from datetime import UTC, datetime

    name = screenshot_name("https://Пример.рф/путь?q=1", datetime(2026, 11, 1, 12, 0, tzinfo=UTC))
    assert name.startswith("screenshots/") and name.endswith("-20261101-120000.png")
    assert "/" not in name.removeprefix("screenshots/")


# --- the tool ---------------------------------------------------------------------------------


@pytest.fixture
async def tool_app(app_factory: AppFactory, tmp_path: Path) -> FastAPI:
    app = await app_factory(workspace_root=str(tmp_path / "ws"))
    async with app.state.db.sessionmaker() as db:
        await UserService(db).create_owner(OWNER_USERNAME, OWNER_PASSWORD, "Owner")
    app.state.queue = RecordingQueue()
    return app


PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478"
    "da63f8cfc0f01f0005000201a0a2b6e30000000049454e44ae426082"
)


class FakeBrowserSandbox:
    def __init__(self, root: Path, html: str) -> None:
        self.root, self.html = root, html
        self.requests: list[dict[str, Any]] = []

    async def run(
        self, workspace_id: uuid.UUID, argv: list[str], *, timeout_seconds: int
    ) -> SandboxResult:
        raise AssertionError("not used")

    async def health(self) -> dict[str, object]:
        return {"ok": True, "image": "img", "limits": {}, "network": "none"}

    async def browse(self, workspace_id: uuid.UUID, request: dict[str, Any]) -> SandboxResult:
        self.requests.append(request)
        ws = self.root / str(workspace_id)
        (ws / request["screenshot"]).write_bytes(PNG)
        (ws / request["dom"]).write_text(self.html)
        return SandboxResult(exit_code=0, stdout="", stderr="")


async def _browse_task(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, tmp: Path, html: str
) -> tuple[Any, ...]:
    from app.workers import jobs

    sandbox = FakeBrowserSandbox(tmp / "ws", html)
    monkeypatch.setattr(jobs, "make_sandbox", lambda settings: sandbox)
    monkeypatch.setattr(app.state.settings, "sandbox_url", "http://sandbox:8090")
    monkeypatch.setattr(app.state.settings, "sandbox_runner_token", SecretStr("t" * 32))
    monkeypatch.setattr(web, "RESOLVE", lambda h, p: asyncio.sleep(0, ["93.184.215.14"]))
    monkeypatch.setattr(
        mock_provider,
        "_handlers",
        [scripted(("browser_screenshot", {"url": "https://example.org/"}), "Seen.")],
    )
    async with logged_in_client(app) as client:
        agent = await tool_agent(client, autonomy="balanced", tools=["browser_screenshot"])
        task_id = (await run_agent(client, agent["id"], "Look at the site")).json()["task"]["id"]
        await drain(app, app.state.queue)
        waiting = await approvals(app, task_id)
        assert [a.status for a in waiting] == ["pending"]  # sensitive: always asks first
        assert (await decide(client, waiting[0].id, "approve")).status_code == 200
        await drain(app, app.state.queue)
        detail = (await client.get(f"/api/v1/tasks/{task_id}")).json()
    return sandbox, detail, (await tool_calls(app, task_id))[0]


async def test_browser_tool_needs_approval_and_saves_a_screenshot(
    tool_app: FastAPI,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = (
        "<html><head><title>Ферма</title></head>"
        "<body><p>Молоко 90 ₽</p><script>x()</script></body></html>"
    )
    sandbox, detail, call = await _browse_task(tool_app, monkeypatch, tmp_path, html)
    assert detail["task"]["status"] == "completed"
    assert (
        sandbox.requests[0]["mode"] == "page"
        and sandbox.requests[0]["url"] == "https://example.org/"
    )
    assert call.status == "succeeded" and "Title: Ферма" in (call.result or "")
    assert 'trust="untrusted"' in (call.result or "") and "Молоко 90" in (call.result or "")
    shots = list((tmp_path / "ws").glob("*/screenshots/example.org-*.png"))
    assert len(shots) == 1 and not list(
        (tmp_path / "ws").glob("*/.browser/*.html")
    )  # page HTML removed


async def test_browser_reports_blocked_private_redirects(
    tool_app: FastAPI,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _detail, call = await _browse_task(
        tool_app,
        monkeypatch,
        tmp_path,
        "<html><body>moloko egress: private or local address</body></html>",
    )
    assert call.status == "failed" and "private or local" in (call.result or "")


# --- export -----------------------------------------------------------------------------------


class FakePrinter(FakeBrowserSandbox):
    async def browse(self, workspace_id: uuid.UUID, request: dict[str, Any]) -> SandboxResult:
        self.requests.append(request)
        ws = self.root / str(workspace_id)
        assert (ws / request["source"]).read_text().startswith("<!doctype html>")
        (ws / request["pdf"]).write_bytes(b"%PDF-1.4 fake")
        return SandboxResult(exit_code=0, stdout="", stderr="")


async def test_result_exports_to_markdown_and_pdf(
    tool_app: FastAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.workers import jobs
    from tests.conftest import add_mock_model, create_agent, csrf_headers

    async with logged_in_client(tool_app) as client:
        await add_mock_model(client)
        agent = await create_agent(client, name="Writer")
        task_id = (await run_agent(client, agent["id"], "Обзор", "молоко")).json()["task"]["id"]
        await drain(tool_app, tool_app.state.queue)

        md = await client.get(f"/api/v1/tasks/{task_id}/export.md")
        assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
        assert md.text.startswith("# Обзор") and "## Результат / Result" in md.text
        assert "attachment" in md.headers["content-disposition"]

        missing = await client.post(
            f"/api/v1/tasks/{task_id}/export.pdf", headers=await csrf_headers(client)
        )
        assert missing.status_code == 409 and missing.json()["error"]["code"] == "pdf_unavailable"

        printer = FakePrinter(tmp_path / "ws", "")
        monkeypatch.setattr(jobs, "make_sandbox", lambda settings: printer)
        pdf = await client.post(
            f"/api/v1/tasks/{task_id}/export.pdf", headers=await csrf_headers(client)
        )
        assert pdf.status_code == 200 and pdf.content == b"%PDF-1.4 fake"
        assert pdf.headers["content-type"] == "application/pdf"
        assert printer.requests[0]["mode"] == "pdf"
        ws = (await client.get(f"/api/v1/tasks/{task_id}/workspace")).json()
        files = (await client.get(f"/api/v1/workspaces/{ws['id']}/files?path=exports")).json()
        pdfs = [
            str(f.get("path", f.get("name", "")))
            for f in files
            if str(f.get("path", f.get("name", ""))).endswith(".pdf")
        ]
        assert pdfs
        rel = pdfs[0] if pdfs[0].startswith("exports/") else f"exports/{pdfs[0]}"
        raw = await client.get(f"/api/v1/workspaces/{ws['id']}/raw", params={"path": rel})
        assert raw.status_code == 200 and raw.content == b"%PDF-1.4 fake"
        assert raw.headers["content-disposition"].startswith("attachment")
        text_file = await client.get(
            f"/api/v1/workspaces/{ws['id']}/raw", params={"path": "notes.txt"}
        )
        assert text_file.status_code in (404, 422)
