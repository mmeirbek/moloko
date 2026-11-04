"""The backend's side of the `codex` service (app/codex_service/server.py): OpenAI's Codex CLI
signed in with the owner's ChatGPT account (owner's decision 2026-11-04). The token between
them is never logged; prompts are never logged either."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx2

from app.core.config import Settings
from app.providers.base import ErrorKind, ModelInfo, ProviderError


@dataclass(frozen=True)
class CodexStatus:
    configured: bool  # CODEX_URL is set
    reachable: bool
    logged_in: bool
    mode: str | None  # "chatgpt" | "api_key"
    version: str


class CodexClient:
    def __init__(
        self, settings: Settings, transport: httpx2.AsyncBaseTransport | None = None
    ) -> None:
        self.url = settings.codex_url.rstrip("/") if settings.codex_url else None
        token = settings.codex_service_token
        self._headers = {"Authorization": f"Bearer {token.get_secret_value()}"} if token else {}
        self._timeout = settings.codex_run_timeout_seconds
        self._transport = transport

    @property
    def configured(self) -> bool:
        return self.url is not None

    def _client(self, timeout: float) -> httpx2.AsyncClient:
        if self.url is None:
            raise ProviderError("unavailable", "Codex is not set up (CODEX_URL)", provider="codex")
        return httpx2.AsyncClient(
            base_url=self.url,
            headers=self._headers,
            timeout=httpx2.Timeout(timeout, connect=10),
            transport=self._transport,
        )

    async def status(self) -> CodexStatus:
        if self.url is None:
            return CodexStatus(False, False, False, None, "")
        try:
            async with self._client(40) as client:
                resp = await client.get("/v1/status")
            data = resp.json() if resp.status_code == 200 else {}
        except (httpx2.HTTPError, ValueError):
            return CodexStatus(True, False, False, None, "")
        return CodexStatus(
            True,
            resp.status_code == 200,
            bool(data.get("logged_in")),
            data.get("mode"),
            str(data.get("version") or ""),
        )

    async def models(self) -> list[ModelInfo]:
        try:
            async with self._client(90) as client:
                resp = await client.get("/v1/models")
        except httpx2.HTTPError as exc:
            raise ProviderError("unavailable", str(exc)[:200], provider="codex") from None
        if resp.status_code == 401:
            raise ProviderError("auth_failed", "codex service token", provider="codex")
        if resp.status_code != 200:
            raise ProviderError("unavailable", resp.text[:200], provider="codex")
        return [ModelInfo(id=m["id"], display_name=m.get("name")) for m in resp.json()]

    async def run(
        self,
        *,
        cwd: str,
        prompt: str,
        model: str | None,
        thread_id: str | None,
        wait_seconds: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Codex's events (``codex exec --json``), then ``{"type": "moloko.exit", ...}``.
        Leaving the iteration early (a stop) ends the run in the service."""
        body: dict[str, Any] = {
            "cwd": cwd,
            "prompt": prompt,
            "model": model,
            "thread_id": thread_id,
        }
        if wait_seconds is not None:
            body["wait_seconds"] = wait_seconds
        try:
            async with (
                self._client(self._timeout + 60) as client,
                client.stream("POST", "/v1/run", json=body) as resp,
            ):
                if resp.status_code != 200:
                    detail = (await resp.aread()).decode(errors="replace")[:200]
                    kind: ErrorKind = "auth_failed" if resp.status_code == 401 else "unavailable"
                    raise ProviderError(kind, detail, provider="codex")
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(event, dict):
                        yield event
        except httpx2.HTTPError as exc:
            raise ProviderError("unavailable", str(exc)[:200], provider="codex") from None
