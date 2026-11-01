"""The sandbox runner against a real Docker daemon (spec 16). Skipped without Docker.

Verifies the limits the spec requires: non-root, read-only root filesystem, no network,
no Docker socket, no capabilities, memory limit, wall-clock timeout, workspace-only
filesystem, token-protected API.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import httpx2
import pytest

from app.sandbox.runner import RunnerSettings, create_runner_app

SOCKET = "/var/run/docker.sock"
pytestmark = pytest.mark.skipif(not os.path.exists(SOCKET), reason="needs a Docker daemon")
TOKEN = "s" * 40


@pytest.fixture
def workspaces(tmp_path: Path) -> Path:
    root = tmp_path / "workspaces"
    root.mkdir()
    return root


async def run(
    workspaces: Path, ws: uuid.UUID, argv: list[str], *, token: str = TOKEN, limit: int = 10
) -> Any:
    settings = RunnerSettings(
        sandbox_runner_token=TOKEN,
        sandbox_workspaces_host_path=str(workspaces),
        sandbox_timeout_seconds=5,
        sandbox_memory_mb=128,
    )
    app = create_runner_app(settings)
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="http://runner",
        headers={"Authorization": f"Bearer {token}"},
        timeout=180,
    ) as client:
        return await client.post(
            "/v1/run", json={"workspace_id": str(ws), "argv": argv, "timeout_seconds": limit}
        )


def new_ws(workspaces: Path) -> uuid.UUID:
    ws = uuid.uuid4()
    (workspaces / str(ws)).mkdir()
    os.chmod(workspaces / str(ws), 0o777)  # noqa: S103 — the sandbox user (10001) writes here
    return ws


async def test_sandbox_isolation(workspaces: Path) -> None:
    ws, other = new_ws(workspaces), new_ws(workspaces)
    (workspaces / str(other) / "private.txt").write_text("other task")
    probe = (
        "import os, socket, pathlib\n"
        "print('uid', os.getuid())\n"
        "try:\n open('/etc/x', 'w')\nexcept OSError as e: print('rootfs', e.errno)\n"
        "try:\n socket.create_connection(('1.1.1.1', 80), 2)\n"
        "except OSError as e: print('net', e.errno)\n"
        "print('sock', os.path.exists('/var/run/docker.sock'))\n"
        "print('caps', open('/proc/self/status').read().split('CapEff:')[1].split()[0])\n"
        "print('files', sorted(p.name for p in pathlib.Path('/workspace').iterdir()))\n"
        "pathlib.Path('/workspace/made.txt').write_text('ok')\n"
    )
    (workspaces / str(ws) / "probe.py").write_text(probe)
    resp = await run(workspaces, ws, ["python", "probe.py"])
    assert resp.status_code == 200, resp.text
    out = resp.json()["stdout"]
    assert "uid 10001" in out  # not root
    assert "rootfs 30" in out  # EROFS: read-only root filesystem
    assert "net 101" in out  # ENETUNREACH: no network
    assert "sock False" in out  # no Docker socket inside
    assert "caps 0000000000000000" in out  # no capabilities
    assert "files ['probe.py']" in out  # only its own workspace is visible
    assert (workspaces / str(ws) / "made.txt").read_text() == "ok"


async def test_sandbox_limits(workspaces: Path) -> None:
    ws = new_ws(workspaces)
    slow = (await run(workspaces, ws, ["sleep", "30"], limit=3)).json()
    assert slow["timed_out"] is True and slow["exit_code"] is None and slow["duration_ms"] < 15000
    hungry = (
        await run(workspaces, ws, ["python", "-c", "x = bytearray(400 * 1024 * 1024)"])
    ).json()
    assert hungry["oom_killed"] is True or hungry["exit_code"] != 0


async def test_sandbox_api_needs_the_token(workspaces: Path) -> None:
    assert (await run(workspaces, new_ws(workspaces), ["ls"], token="wrong")).status_code == 401
