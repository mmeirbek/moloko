"""Sandbox runner service (spec 16) — the only component that talks to Docker.

It runs as its own container with the Docker socket; the backend and worker never get
the socket. It accepts one kind of request from the worker (token-protected): run this
argv in that workspace. Everything else is fixed here, not by the caller:

* image: ``SANDBOX_IMAGE``; no network (``NetworkMode: none``);
* non-root (uid 10001), read-only root filesystem, ``cap_drop: ALL``,
  ``no-new-privileges``, ``/tmp`` as a small tmpfs, pids / memory / CPU limits;
* only the workspace is mounted (a named-volume subpath), never the Docker socket,
  never host secrets, no environment from the host;
* wall-clock timeout (killed when exceeded); output capped; the container is removed.

Its settings deliberately contain no database, Redis or app secrets.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import re
import secrets
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.sandbox.docker_api import DockerApi, DockerError

logger = logging.getLogger("moloko.sandbox")

LABEL = "moloko.sandbox"
SANDBOX_UID = "10001:10001"


class RunnerSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    sandbox_runner_token: SecretStr | None = None  # unset/short = refuse every run
    sandbox_image: str = "python:3.12.16-slim"
    sandbox_cpus: float = Field(1.0, gt=0, le=16)
    sandbox_memory_mb: int = Field(512, ge=64, le=65_536)
    sandbox_pids_limit: int = Field(128, ge=16, le=4096)
    sandbox_timeout_seconds: int = Field(60, ge=1, le=3600)
    sandbox_output_max_bytes: int = Field(64_000, ge=1000, le=10_000_000)
    sandbox_max_concurrent: int = Field(2, ge=1, le=16)
    sandbox_workspaces_volume: str | None = "moloko_workspaces"
    sandbox_workspaces_host_path: str | None = None
    docker_socket: str = "/var/run/docker.sock"
    # The agents' browser: headless Chromium in its own container on an internal network
    # whose only exit is the egress proxy (app/sandbox/egress.py). PDF export: no network.
    sandbox_browser_image: str = "moloko-browser:local"
    sandbox_browser_binary: str = "chromium-headless-shell"  # Debian package of that name
    sandbox_browser_network: str = "moloko_browser"
    sandbox_browser_proxy: str = "http://egress:3128"
    sandbox_browser_memory_mb: int = Field(1024, ge=256, le=8192)
    sandbox_browser_timeout_seconds: int = Field(45, ge=5, le=300)


class RunRequest(BaseModel):
    model_config = {"extra": "forbid"}

    workspace_id: uuid.UUID
    argv: list[Annotated[str, Field(max_length=8000)]] = Field(min_length=1, max_length=200)
    timeout_seconds: int = Field(ge=1, le=3600)


# Where the browser may write inside the workspace (checked again here, not trusted).
BROWSER_OUTPUT = re.compile(
    r"^(screenshots/[\w.-]{1,80}\.png|exports/[\w.-]{1,80}\.pdf|\.browser/[a-f0-9]{8,40}\.html)$"
)
BROWSER_INPUT = re.compile(r"^\.browser/[a-f0-9]{8,40}\.html$")


class BrowseRequest(BaseModel):
    """``page``: open a public URL (through the egress proxy), save a screenshot and the
    page's HTML. ``pdf``: print an HTML file from the workspace to PDF, with no network."""

    model_config = {"extra": "forbid"}

    workspace_id: uuid.UUID
    mode: Literal["page", "pdf"]
    url: str | None = Field(default=None, max_length=2000)
    source: str | None = Field(default=None, max_length=200)
    screenshot: str | None = Field(default=None, max_length=200)
    dom: str | None = Field(default=None, max_length=200)
    pdf: str | None = Field(default=None, max_length=200)
    width: int = Field(1280, ge=320, le=1920)
    height: int = Field(900, ge=320, le=4000)


CHROMIUM_FLAGS = (
    "--no-sandbox --disable-gpu --disable-dev-shm-usage --no-first-run "
    "--no-default-browser-check --disable-extensions --disable-sync "
    "--disable-background-networking "
    "--hide-scrollbars --mute-audio --user-data-dir=/tmp/profile --timeout=20000"
)


def browser_command(
    req: BrowseRequest, proxy: str, binary: str = "chromium-headless-shell"
) -> tuple[list[str], bool]:
    """(argv, needs network). The URL and paths are passed as shell *arguments* ($1…),
    never pasted into the script. Raises ValueError for anything off-pattern."""
    size = f"--window-size={req.width},{req.height}"
    if req.mode == "page":
        if not req.url or not req.url.startswith(("http://", "https://")):
            raise ValueError("http(s) URL required")
        if not (
            req.screenshot
            and req.dom
            and BROWSER_OUTPUT.match(req.screenshot)
            and BROWSER_OUTPUT.match(req.dom)
        ):
            raise ValueError("bad output paths")
        proxied = f'{CHROMIUM_FLAGS} --proxy-server="$PROXY" --proxy-bypass-list="<-loopback>"'
        script = (
            f"{binary} {proxied} {size} "
            '--virtual-time-budget=8000 --screenshot="$2" "$1" >/dev/null 2>&1; '
            f"{binary} {proxied} "
            '--virtual-time-budget=8000 --dump-dom "$1" > "$3" 2>/dev/null; test -s "$2"'
        )
        return ["sh", "-c", script, "sh", req.url, req.screenshot, req.dom], True
    if not (
        req.source and req.pdf and BROWSER_INPUT.match(req.source) and BROWSER_OUTPUT.match(req.pdf)
    ):
        raise ValueError("bad pdf paths")
    script = (
        f"mkdir -p exports && {binary} {CHROMIUM_FLAGS} --no-pdf-header-footer "
        '--print-to-pdf="$2" "file:///workspace/$1" >/dev/null 2>&1; test -s "$2"'
    )
    return ["sh", "-c", script, "sh", req.source, req.pdf], False


def browser_spec(settings: RunnerSettings, req: BrowseRequest) -> dict[str, Any]:
    argv, network = browser_command(
        req, settings.sandbox_browser_proxy, settings.sandbox_browser_binary
    )
    spec = container_spec(settings, req.workspace_id, argv)
    memory = settings.sandbox_browser_memory_mb * 1024 * 1024
    spec["Image"] = settings.sandbox_browser_image
    spec["Env"] = ["HOME=/tmp", "LANG=C.UTF-8", f"PROXY={settings.sandbox_browser_proxy}"]
    host = spec["HostConfig"]
    host.update(
        {
            "Memory": memory,
            "MemorySwap": memory,
            "Tmpfs": {"/tmp": "rw,nosuid,nodev,size=256m"},  # noqa: S108 — inside the sandbox
            "ShmSize": 64 * 1024 * 1024,
        }
    )
    if network:  # the internal browser network: its only other member is the egress proxy
        spec["NetworkDisabled"] = False
        host["NetworkMode"] = settings.sandbox_browser_network
    spec["Labels"][f"{LABEL}.kind"] = "browser"
    return spec


class RunResponse(BaseModel):
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    oom_killed: bool
    truncated: bool
    duration_ms: int


def container_spec(
    settings: RunnerSettings, workspace_id: uuid.UUID, argv: list[str]
) -> dict[str, Any]:
    if settings.sandbox_workspaces_host_path:
        mount: dict[str, Any] = {
            "Type": "bind",
            "Source": f"{settings.sandbox_workspaces_host_path.rstrip('/')}/{workspace_id}",
            "Target": "/workspace",
        }
    else:
        mount = {
            "Type": "volume",
            "Source": settings.sandbox_workspaces_volume,
            "Target": "/workspace",
            "VolumeOptions": {"Subpath": str(workspace_id)},
        }
    memory = settings.sandbox_memory_mb * 1024 * 1024
    return {
        "Image": settings.sandbox_image,
        "Cmd": argv,
        "Entrypoint": [],
        "WorkingDir": "/workspace",
        "User": SANDBOX_UID,
        "Env": ["HOME=/tmp", "PYTHONDONTWRITEBYTECODE=1", "PIP_NO_CACHE_DIR=1", "LANG=C.UTF-8"],
        "NetworkDisabled": True,
        "AttachStdout": True,
        "AttachStderr": True,
        "Labels": {LABEL: "1", f"{LABEL}.workspace": str(workspace_id)},
        "HostConfig": {
            "NetworkMode": "none",
            "Memory": memory,
            "MemorySwap": memory,
            "NanoCpus": int(settings.sandbox_cpus * 1e9),
            "PidsLimit": settings.sandbox_pids_limit,
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "Privileged": False,
            "Init": True,
            "IpcMode": "private",
            "Tmpfs": {"/tmp": "rw,nosuid,nodev,size=64m"},  # noqa: S108 — inside the sandbox
            "Mounts": [mount],
            "Ulimits": [{"Name": "nofile", "Soft": 1024, "Hard": 1024}],
            "LogConfig": {"Type": "json-file", "Config": {"max-size": "1m"}},
        },
    }


class Runner:
    def __init__(self, settings: RunnerSettings, docker: DockerApi | None = None) -> None:
        self.settings = settings
        self.docker = docker or DockerApi(settings.docker_socket)
        self._slots = asyncio.Semaphore(settings.sandbox_max_concurrent)
        self._image_ready = False

    async def _ensure_image(self) -> None:
        if self._image_ready:
            return
        if not await self.docker.image_exists(self.settings.sandbox_image):
            await self.docker.pull(self.settings.sandbox_image)
        self._image_ready = True

    async def run(self, req: RunRequest) -> RunResponse:
        timeout = min(req.timeout_seconds, self.settings.sandbox_timeout_seconds)
        async with self._slots:
            await self._ensure_image()
            name = f"moloko-sbx-{str(req.workspace_id)[:8]}-{secrets.token_hex(4)}"
            cid = await self.docker.create(
                name, container_spec(self.settings, req.workspace_id, req.argv)
            )
            started = time.monotonic()
            timed_out = False
            try:
                await self.docker.start(cid)
                try:
                    await asyncio.wait_for(self.docker.wait(cid, timeout + 10), timeout=timeout)
                except TimeoutError:
                    timed_out = True
                    await self.docker.kill(cid)
                    await self.docker.wait(cid, 15)
                state = (await self.docker.inspect(cid)).get("State", {})
                stdout, stderr, truncated = await self.docker.logs(
                    cid, self.settings.sandbox_output_max_bytes
                )
            finally:
                await self.docker.remove(cid)
        return RunResponse(
            exit_code=None if timed_out else state.get("ExitCode"),
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            oom_killed=bool(state.get("OOMKilled")),
            truncated=truncated,
            duration_ms=int((time.monotonic() - started) * 1000),
        )


class BrowserRunner(Runner):
    async def _ensure_browser(self) -> None:
        if not await self.docker.image_exists(self.settings.sandbox_browser_image):
            raise DockerError(
                "browser image missing (build infrastructure/docker/browser.Dockerfile)"
            )

    async def browse(self, req: BrowseRequest) -> RunResponse:
        timeout = self.settings.sandbox_browser_timeout_seconds
        spec = browser_spec(self.settings, req)
        async with self._slots:
            await self._ensure_browser()
            name = f"moloko-web-{str(req.workspace_id)[:8]}-{secrets.token_hex(4)}"
            cid = await self.docker.create(name, spec)
            started = time.monotonic()
            timed_out = False
            try:
                await self.docker.start(cid)
                try:
                    await asyncio.wait_for(self.docker.wait(cid, timeout + 10), timeout=timeout)
                except TimeoutError:
                    timed_out = True
                    await self.docker.kill(cid)
                    await self.docker.wait(cid, 15)
                state = (await self.docker.inspect(cid)).get("State", {})
                stdout, stderr, truncated = await self.docker.logs(cid, 8000)
            finally:
                await self.docker.remove(cid)
        return RunResponse(
            exit_code=None if timed_out else state.get("ExitCode"),
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            oom_killed=bool(state.get("OOMKilled")),
            truncated=truncated,
            duration_ms=int((time.monotonic() - started) * 1000),
        )


def create_runner_app(
    settings: RunnerSettings | None = None, docker: DockerApi | None = None
) -> FastAPI:
    settings = settings or RunnerSettings()
    runner = BrowserRunner(settings, docker)
    token = (
        settings.sandbox_runner_token.get_secret_value() if settings.sandbox_runner_token else ""
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield

    app = FastAPI(
        title="moloko sandbox runner",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.runner = runner

    def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
        given = (authorization or "").removeprefix("Bearer ").strip()
        if len(token) < 24 or not given or not hmac.compare_digest(given.encode(), token.encode()):
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.get("/v1/health")
    async def health() -> dict[str, object]:
        return {
            "ok": len(token) >= 24 and await runner.docker.ping(),
            "image": settings.sandbox_image,
            "limits": {
                "cpus": settings.sandbox_cpus,
                "memory_mb": settings.sandbox_memory_mb,
                "pids": settings.sandbox_pids_limit,
                "timeout_seconds": settings.sandbox_timeout_seconds,
            },
            "network": "none",
        }

    @app.post("/v1/run", response_model=RunResponse, dependencies=[Depends(require_token)])
    async def run(req: RunRequest) -> RunResponse:
        try:
            return await runner.run(req)
        except DockerError as exc:
            logger.warning("sandbox_docker_error", extra={"error": str(exc)[:300]})
            raise HTTPException(status_code=502, detail="docker error") from None

    @app.post("/v1/browse", response_model=RunResponse, dependencies=[Depends(require_token)])
    async def browse(req: BrowseRequest) -> RunResponse:
        try:
            return await runner.browse(req)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except DockerError as exc:
            logger.warning("sandbox_docker_error", extra={"error": str(exc)[:300]})
            raise HTTPException(status_code=502, detail="docker error") from None

    return app


def app() -> FastAPI:  # uvicorn --factory app.sandbox.runner:app
    return create_runner_app()
