"""The sandbox container spec and the runner's answers (no Docker needed)."""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx2
import pytest
from pydantic import SecretStr

from app.sandbox.base import SandboxUnavailable
from app.sandbox.client import RunnerSandbox
from app.sandbox.docker_api import DockerApi
from app.sandbox.runner import RunnerSettings, container_spec, create_runner_app
from app.services.workspaces import snapshot
from tests.conftest import make_settings


def test_the_task_folder_is_mounted_without_copy_up() -> None:
    """Without NoCopy, Docker copies the image's root-owned /workspace onto an empty task
    folder and hands it to root: the agent then cannot write its own files."""
    wid = uuid.uuid4()
    spec = container_spec(RunnerSettings(sandbox_workspaces_volume="ws"), wid, ["true"])
    mount = spec["HostConfig"]["Mounts"][0]
    assert mount["Type"] == "volume" and mount["Target"] == "/workspace"
    assert mount["VolumeOptions"] == {"Subpath": str(wid), "NoCopy": True}
    assert spec["User"] == "10001:10001" and spec["WorkingDir"] == "/workspace"


# --- the command image ------------------------------------------------------------------------


def test_commands_run_in_the_image_with_node_by_default() -> None:
    spec = container_spec(RunnerSettings(), uuid.uuid4(), ["node", "--version"])
    assert spec["Image"] == "moloko-sandbox:local"
    assert spec["HostConfig"]["NetworkMode"] == "none" and spec["NetworkDisabled"] is True
    assert {"node", "npm", "npx", "git", "python"} <= set(make_settings().sandbox_allowed_commands)


def test_browser_tests_have_room_and_reach_localhost_directly() -> None:
    """Playwright + Chromium: shared memory, a bigger /tmp, more open files; a test server in
    the same container is never reached through the package proxy."""
    spec = container_spec(RunnerSettings(), uuid.uuid4(), ["npx", "playwright", "test"], "packages")
    host = spec["HostConfig"]
    assert host["ShmSize"] == 256 * 1024 * 1024
    assert host["Tmpfs"]["/tmp"].endswith("size=256m")  # noqa: S108 — inside the sandbox
    assert host["Ulimits"] == [{"Name": "nofile", "Soft": 4096, "Hard": 4096}]
    env = dict(e.split("=", 1) for e in spec["Env"])
    assert env["NO_PROXY"] == env["no_proxy"] == "localhost,127.0.0.1,::1"
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == "/workspace/.cache/ms-playwright"
    assert env["CHROMIUM_PATH"] == "/usr/bin/chromium-headless-shell"
    assert host["ReadonlyRootfs"] is True and host["CapDrop"] == ["ALL"]  # nothing loosened
    hosts = make_settings().sandbox_package_hosts
    assert {"cdn.playwright.dev", "playwright.download.prss.microsoft.com"} <= set(hosts)


def runner_sandbox(docker: httpx2.MockTransport) -> RunnerSandbox:
    """The worker's client talking to a runner whose Docker API is ``docker``."""
    runner = create_runner_app(
        RunnerSettings(sandbox_runner_token=SecretStr("t" * 32)),
        DockerApi("/nowhere", transport=docker),
    )
    settings = make_settings(
        sandbox_url="http://sandbox:8090", sandbox_runner_token=SecretStr("t" * 32)
    )
    return RunnerSandbox(settings, transport=httpx2.ASGITransport(app=runner))


async def test_a_missing_command_image_is_reported_clearly() -> None:
    seen: list[str] = []

    def docker(request: httpx2.Request) -> httpx2.Response:
        seen.append(f"{request.method} {request.url.path}")
        return httpx2.Response(404, json={"message": "No such image"})

    sandbox = runner_sandbox(httpx2.MockTransport(docker))
    with pytest.raises(SandboxUnavailable, match="not installed"):
        await sandbox.run(uuid.uuid4(), ["node", "-v"], timeout_seconds=5)
    assert "POST /v1.45/images/create" in seen  # tried a pull first, then a clear answer
    assert not any("/containers/create" in s for s in seen)


def test_dependency_folders_are_not_scanned_for_changes(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.ts").write_text("x")
    for skipped in ("node_modules/react", "web/node_modules/x", ".cache/npm", ".venv"):
        (tmp_path / skipped).mkdir(parents=True)
        (tmp_path / skipped / "f.js").write_text("y")
    found = snapshot(tmp_path, 100, make_settings().workspace_untracked_dirs)
    assert sorted(found) == ["src/app.ts"]
    assert len(snapshot(tmp_path, 100)) == 5  # nothing skipped without the list
