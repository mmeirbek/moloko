"""Worker side: call the sandbox runner over the internal Docker network."""

from __future__ import annotations

import uuid

import httpx2

from app.core.config import Settings
from app.sandbox.base import SandboxResult, SandboxUnavailable


class RunnerSandbox:
    def __init__(
        self, settings: Settings, transport: httpx2.AsyncBaseTransport | None = None
    ) -> None:
        if not settings.sandbox_url or settings.sandbox_runner_token is None:
            raise SandboxUnavailable("The sandbox is not configured (SANDBOX_URL).")
        self._url = settings.sandbox_url.rstrip("/")
        self._token = settings.sandbox_runner_token.get_secret_value()
        self._transport = transport
        self._timeout = settings.sandbox_timeout_seconds

    def _client(self, timeout: float) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            base_url=self._url,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=timeout,
            transport=self._transport,
        )

    async def run(
        self, workspace_id: uuid.UUID, argv: list[str], *, timeout_seconds: int
    ) -> SandboxResult:
        try:
            async with self._client(timeout_seconds + 30) as client:
                resp = await client.post(
                    "/v1/run",
                    json={
                        "workspace_id": str(workspace_id),
                        "argv": argv,
                        "timeout_seconds": timeout_seconds,
                    },
                )
        except httpx2.HTTPError as exc:
            raise SandboxUnavailable("The sandbox service cannot be reached.") from exc
        if resp.status_code != 200:
            raise SandboxUnavailable(f"The sandbox refused the command (HTTP {resp.status_code}).")
        data = resp.json()
        return SandboxResult(
            exit_code=data.get("exit_code"),
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            timed_out=bool(data.get("timed_out")),
            oom_killed=bool(data.get("oom_killed")),
            truncated=bool(data.get("truncated")),
            duration_ms=int(data.get("duration_ms", 0)),
        )

    async def browse(self, workspace_id: uuid.UUID, request: dict[str, object]) -> SandboxResult:
        """Headless browser in the sandbox: a screenshot of a public page, or HTML → PDF."""
        try:
            async with self._client(120) as client:
                resp = await client.post(
                    "/v1/browse", json={"workspace_id": str(workspace_id), **request}
                )
        except httpx2.HTTPError as exc:
            raise SandboxUnavailable("The sandbox service cannot be reached.") from exc
        if resp.status_code != 200:
            raise SandboxUnavailable(f"The browser could not run (HTTP {resp.status_code}).")
        data = resp.json()
        return SandboxResult(
            exit_code=data.get("exit_code"),
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            timed_out=bool(data.get("timed_out")),
            oom_killed=bool(data.get("oom_killed")),
            truncated=bool(data.get("truncated")),
            duration_ms=int(data.get("duration_ms", 0)),
        )

    async def health(self) -> dict[str, object]:
        try:
            async with self._client(5) as client:
                resp = await client.get("/v1/health")
            return dict(resp.json()) if resp.status_code == 200 else {"ok": False}
        except httpx2.HTTPError:
            return {"ok": False}
