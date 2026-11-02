"""Package downloads in the sandbox (terminal_run network "packages"): the registries-only
egress proxy, the container spec, the approval, standing approvals."""

from __future__ import annotations

import asyncio
import ssl
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from app.providers import mock_provider
from app.sandbox.egress import EgressProxy, host_allowed, serve, server_name
from app.sandbox.runner import RunnerSettings, RunRequest, container_spec
from app.services.users import UserService
from app.tools import standing
from tests.conftest import (
    OWNER_PASSWORD,
    OWNER_USERNAME,
    AppFactory,
    RecordingQueue,
    drain,
    logged_in_client,
    run_agent,
)
from tests.test_tools_integrations import FakeSandbox
from tests.tools_helpers import approvals, decide, scripted, tool_agent, tool_calls

# --- the registries-only egress proxy ---------------------------------------------------------


def client_hello(server_hostname: str) -> bytes:
    """A real TLS ClientHello (Python's ssl), as npm or pip would send it."""
    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
    tls = ssl.create_default_context().wrap_bio(incoming, outgoing, server_hostname=server_hostname)
    with pytest.raises(ssl.SSLWantReadError):
        tls.do_handshake()
    return outgoing.read()


def test_the_tls_server_name_is_read_from_a_client_hello() -> None:
    hello = client_hello("Registry.NPMjs.org")
    assert hello[0] == 0x16 and server_name(hello[9:]) == "registry.npmjs.org"
    assert server_name(b"\x03\x03" + b"\x00" * 10) is None  # cut short: no name, no crash


def test_hosts_are_matched_exactly_or_by_wildcard() -> None:
    allowed = ("registry.npmjs.org", "*.pythonhosted.org")
    assert host_allowed("REGISTRY.npmjs.org.", allowed)
    assert host_allowed("files.pythonhosted.org", allowed)
    for bad in (
        "npmjs.org",
        "evil-registry.npmjs.org",
        "registry.npmjs.org.evil.com",
        "pythonhosted.org",
    ):
        assert not host_allowed(bad, allowed)


async def _origin(received: list[bytes]) -> tuple[asyncio.Server, int]:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        received.append(await reader.read(65_536))
        writer.write(b"from-origin")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def _tunnel(proxy_port: int, target: str, first: bytes) -> tuple[bytes, bytes]:
    """CONNECT, then send ``first``: (the proxy's answer, what came back through it)."""
    reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
    writer.write(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
    await writer.drain()
    head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
    if b" 200 " not in head:  # refused: the answer with its reason
        head += await asyncio.wait_for(reader.read(65_536), 5)
        writer.close()
        return head, b""
    writer.write(first)
    await writer.drain()
    back = await asyncio.wait_for(reader.read(65_536), 5)
    writer.close()
    return head, back


@pytest.fixture
async def registry_proxy() -> Any:
    received: list[bytes] = []
    origin, port = await _origin(received)
    proxy = EgressProxy(
        allowed_ports=(port,),
        allowed_hosts=("registry.test",),
        resolver=lambda h, p: asyncio.sleep(0, ["127.0.0.1"]),
        allow_private=True,  # the test origin is on loopback
    )
    server = await serve(proxy, "127.0.0.1", 0)
    try:
        yield server.sockets[0].getsockname()[1], port, received
    finally:
        server.close()
        origin.close()


async def test_only_tls_to_an_allowed_registry_goes_through(registry_proxy: Any) -> None:
    pport, port, received = registry_proxy
    hello = client_hello("registry.test")
    head, back = await _tunnel(pport, f"registry.test:{port}", hello)
    assert b" 200 " in head and back == b"from-origin"
    assert received == [hello]  # the origin got the client's TLS start unchanged


async def test_other_hosts_plain_http_and_other_tls_names_are_refused(
    registry_proxy: Any,
) -> None:
    pport, port, received = registry_proxy
    head, _ = await _tunnel(pport, f"evil.test:{port}", b"")
    assert b" 403 " in head and b"allow-list" in head
    reader, writer = await asyncio.open_connection("127.0.0.1", pport)
    writer.write(
        f"GET http://registry.test:{port}/ HTTP/1.1\r\nHost: registry.test\r\n\r\n".encode()
    )
    await writer.drain()
    plain = await asyncio.wait_for(reader.read(65_536), 5)
    writer.close()
    assert b" 403 " in plain.split(b"\r\n")[0] and b"only HTTPS" in plain
    # an allowed CONNECT, but the TLS inside asks for another site (CDN domain fronting)
    head, back = await _tunnel(pport, f"registry.test:{port}", client_hello("evil.test"))
    assert b" 200 " in head and back == b""
    head, back = await _tunnel(pport, f"registry.test:{port}", b"GET / HTTP/1.1\r\n\r\n")
    assert back == b""  # not TLS at all
    assert received == []  # nothing reached the origin


# --- the container ------------------------------------------------------------------------------


def test_package_downloads_get_only_the_proxy_network() -> None:
    settings = RunnerSettings()
    wid = uuid.uuid4()
    offline = container_spec(settings, wid, ["npm", "ci"])
    online = container_spec(settings, wid, ["npm", "ci"], "packages")
    assert offline["HostConfig"]["NetworkMode"] == "none" and offline["NetworkDisabled"] is True
    assert not any("PROXY" in e.upper() for e in offline["Env"])
    assert online["HostConfig"]["NetworkMode"] == "moloko_packages"
    assert online["NetworkDisabled"] is False
    for name in ("HTTPS_PROXY", "https_proxy", "npm_config_https_proxy", "npm_config_proxy"):
        assert f"{name}=http://egress-packages:3128" in online["Env"]
    assert "npm_config_cache=/workspace/.cache/npm" in online["Env"]
    # everything else stays as locked down as without network
    for key in ("ReadonlyRootfs", "CapDrop", "SecurityOpt", "Memory", "PidsLimit", "Mounts"):
        assert online["HostConfig"][key] == offline["HostConfig"][key]
    assert online["User"] == offline["User"] == "10001:10001"


def test_the_runner_accepts_only_known_networks() -> None:
    base = {"workspace_id": str(uuid.uuid4()), "argv": ["npm", "ci"], "timeout_seconds": 5}
    assert RunRequest(**base).network == "none"
    assert RunRequest(**base, network="packages").network == "packages"
    with pytest.raises(ValueError):
        RunRequest(**base, network="bridge")


# --- the tool: approval and standing approvals ---------------------------------------------------


@pytest.fixture
async def tool_app(app_factory: AppFactory, tmp_path: Path) -> FastAPI:
    app = await app_factory(workspace_root=str(tmp_path / "ws"))
    async with app.state.db.sessionmaker() as db:
        await UserService(db).create_owner(OWNER_USERNAME, OWNER_PASSWORD, "Owner")
    app.state.queue = RecordingQueue()
    return app


async def test_package_downloads_need_approval_and_run_on_the_proxy_network(
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
        [
            scripted(
                ("terminal_run", {"command": "npm --version"}),
                ("terminal_run", {"command": "npm ci", "network": "packages"}),
                "done",
            )
        ],
    )
    async with logged_in_client(tool_app) as client:
        agent = await tool_agent(client, autonomy="balanced", tools=["terminal_run"])
        task_id = (await run_agent(client, agent["id"], "Install")).json()["task"]["id"]
        await drain(tool_app, tool_app.state.queue)
        calls = await tool_calls(tool_app, task_id)
        assert (calls[0].category, calls[0].status) == ("write", "succeeded")  # offline: as before
        assert (calls[1].category, calls[1].status) == ("sensitive", "awaiting_approval")
        [pending] = await approvals(tool_app, task_id)
        assert "internet: registry.npmjs.org (HTTPS)" in pending.resources
        assert pending.summary == "Run with package downloads: npm ci"
        assert (await decide(client, pending.id, "approve")).status_code == 200
        await drain(tool_app, tool_app.state.queue)
    assert sandbox.networks == ["none", "packages"]
    assert (await tool_calls(tool_app, task_id))[1].status == "succeeded"


async def test_the_restricted_level_never_downloads(
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
        [scripted(("terminal_run", {"command": "pip install x", "network": "packages"}), "ok")],
    )
    async with logged_in_client(tool_app) as client:
        agent = await tool_agent(client, autonomy="restricted", tools=["terminal_run"])
        task_id = (await run_agent(client, agent["id"], "Install")).json()["task"]["id"]
        await drain(tool_app, tool_app.state.queue)
    assert (await tool_calls(tool_app, task_id))[0].status == "denied"
    assert sandbox.networks == []


def test_standing_approvals_keep_downloads_separate() -> None:
    online = {"command": "npm ci", "network": "packages"}
    assert standing.scopes("terminal_run", online) == ["packages:npm"]
    assert standing.scopes("terminal_run", {"command": "npm ci"}) == ["npm"]

    class AgentLike:
        def __init__(self, scopes: list[str]) -> None:
            self.permissions = {
                "always": [{"id": s, "tool": "terminal_run", "scope": s} for s in scopes]
            }

    offline_only = AgentLike(["npm"])
    with_downloads = AgentLike(["packages:npm"])
    assert standing.covering(offline_only, "terminal_run", online) is None  # type: ignore[arg-type]
    assert standing.covering(with_downloads, "terminal_run", online) is not None  # type: ignore[arg-type]
    # allowing npm with downloads also allows it offline, never another program
    assert standing.covering(with_downloads, "terminal_run", {"command": "npm test"}) is not None  # type: ignore[arg-type]
    assert standing.covering(with_downloads, "terminal_run", {"command": "node a.js"}) is None  # type: ignore[arg-type]
