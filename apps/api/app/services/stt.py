"""The local speech-to-text service (`stt` in docker-compose: Whisper on this server's CPU,
`apps/stt`). It speaks the OpenAI ``/v1/audio/transcriptions`` shape and lives on the
internal network only. Unset ``STT_URL`` = no local model (voice uses the provider).
"""

from __future__ import annotations

import time
from typing import Literal

import httpx2

from app.core.config import Settings
from app.core.errors import AppError

LocalStatus = Literal["off", "ready", "loading", "missing", "error", "unreachable"]
_KNOWN = ("ready", "loading", "missing", "error")


class LocalSttFailed(Exception):
    """The local service could not answer (down, timed out, server error)."""


class AudioTooLarge(AppError):
    status_code = 413
    code = "audio_too_large"
    message = "The recording is too long."


class AudioUnreadable(AppError):
    status_code = 422
    code = "audio_unreadable"
    message = "The recording could not be read. Try recording again."


class LocalStt:
    def __init__(
        self, settings: Settings, transport: httpx2.AsyncBaseTransport | None = None
    ) -> None:
        self.url = settings.stt_url.rstrip("/") if settings.stt_url else None
        self.model = settings.stt_model
        self._settings = settings
        self._transport = transport
        self._cached: tuple[float, LocalStatus] | None = None

    @property
    def configured(self) -> bool:
        return self.url is not None

    def _client(self, timeout: float) -> httpx2.AsyncClient:
        assert self.url is not None
        return httpx2.AsyncClient(
            base_url=self.url,
            timeout=httpx2.Timeout(timeout, connect=self._settings.stt_connect_timeout_seconds),
            transport=self._transport,
        )

    def forget(self) -> None:
        self._cached = None

    async def status(self) -> LocalStatus:
        """What the service says on /health (cached briefly: the settings page and every
        recording ask)."""
        if self.url is None:
            return "off"
        now = time.monotonic()
        if self._cached and self._cached[0] > now:
            return self._cached[1]
        status: LocalStatus = "unreachable"
        try:
            async with self._client(self._settings.stt_connect_timeout_seconds) as client:
                resp = await client.get("/health")
            reported = resp.json().get("status") if resp.status_code == 200 else None
            if reported in _KNOWN:
                status = reported
        except (httpx2.HTTPError, ValueError):
            status = "unreachable"
        self._cached = (now + self._settings.stt_health_cache_seconds, status)
        return status

    async def transcribe(
        self, audio: bytes, filename: str, content_type: str | None, language: str | None
    ) -> str:
        data = {"model": self.model, "response_format": "json"}
        if language:
            data["language"] = language
        files = {"file": (filename, audio, content_type or "application/octet-stream")}
        try:
            async with self._client(self._settings.stt_timeout_seconds) as client:
                resp = await client.post("/v1/audio/transcriptions", data=data, files=files)
        except httpx2.HTTPError as exc:
            self.forget()
            raise LocalSttFailed(type(exc).__name__) from exc
        if resp.status_code in (400, 422):
            raise AudioUnreadable()
        if resp.status_code == 413:
            raise AudioTooLarge()
        if resp.status_code != 200:
            self.forget()
            raise LocalSttFailed(f"HTTP {resp.status_code}")
        try:
            return str(resp.json().get("text") or "")
        except ValueError as exc:
            raise LocalSttFailed("bad response") from exc
