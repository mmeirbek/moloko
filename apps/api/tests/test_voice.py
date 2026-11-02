"""Voice input: the local Whisper service first, else the owner's OpenAI-type provider."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx2
from fastapi import FastAPI
from sqlalchemy import select

from app.models import UsageRecord, User
from app.services.stt import LocalStt
from tests.conftest import (
    OWNER_PASSWORD,
    OWNER_USERNAME,
    AppFactory,
    add_mock_model,
    csrf_headers,
    logged_in_client,
)

AUDIO = ("voice.webm", b"\x1aE\xdf\xa3 fake", "audio/webm")


async def owner_app(app_factory: AppFactory, **overrides: Any) -> FastAPI:
    from app.services.users import UserService

    app = await app_factory(**overrides)
    async with app.state.db.sessionmaker() as db:
        await UserService(db).create_owner(OWNER_USERNAME, OWNER_PASSWORD, "Owner")
    return app


class FakeStt:
    """Stands in for the `stt` service (its HTTP API)."""

    def __init__(self, status: str = "ready", fail: bool = False) -> None:
        self.status = status
        self.fail = fail
        self.calls: list[dict[str, str]] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/health":
            return httpx2.Response(200, json={"status": self.status, "model": "small"})
        if self.fail:
            return httpx2.Response(500, json={"error": {"message": "boom"}})
        body = request.content.decode("latin-1")
        language = "ru" if 'name="language"\r\n\r\nru' in body else ""
        self.calls.append({"language": language, "model": "small" if "small" in body else ""})
        return httpx2.Response(200, json={"text": " Привет из Whisper ", "language": "ru"})

    def install(self, app: FastAPI) -> None:
        app.state.stt = LocalStt(app.state.settings, transport=httpx2.MockTransport(self.handler))


async def transcribe(client: Any, language: str | None = None) -> Any:
    return await client.post(
        "/api/v1/ai/transcribe",
        files={"audio": AUDIO},
        data={"language": language} if language is not None else {},
        headers=await csrf_headers(client),
    )


async def test_voice_needs_a_capable_provider_then_transcribes(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        resp = await transcribe(client)
        assert resp.status_code == 409 and resp.json()["error"]["code"] == "ai_service_unavailable"
        info = (await client.get("/api/v1/ai/settings")).json()
        assert info["available"] is False and info["voice_available"] is False
        assert info["voice_engine"] is None and info["local_stt_status"] == "off"

        await add_mock_model(client)
        info = (await client.get("/api/v1/ai/settings")).json()
        assert info["available"] is True and info["transcription_model"]
        assert (
            info["voice_engine"] == "provider"
            and info["voice_model"] == info["transcription_model"]
        )
        resp = await transcribe(client, "ru")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"text": "Привет, moloko"}
        # "" = detect the language (the mic's default): accepted
        assert (await transcribe(client, "")).status_code == 200

        resp = await client.put(
            "/api/v1/ai/settings",
            json={"transcription_model": "whisper-x", "semantic_search": False},
            headers=await csrf_headers(client),
        )
        assert resp.json()["transcription_model"] == "whisper-x"
        assert resp.json()["semantic_search"] is False
    async with app.state.db.sessionmaker() as db:
        rows = (
            await db.execute(select(UsageRecord).where(UsageRecord.source == "voice"))
        ).scalars()
        assert [r.model for r in rows] == [info["transcription_model"]] * 2


async def test_local_whisper_is_used_first_and_costs_nothing(app_factory: AppFactory) -> None:
    app = await owner_app(app_factory, stt_url="http://stt:8000", stt_model="small")
    fake = FakeStt()
    fake.install(app)
    async with logged_in_client(app) as client:
        # no provider at all: the local model alone makes voice available
        info = (await client.get("/api/v1/ai/settings")).json()
        assert info["voice_available"] is True and info["available"] is False
        assert info["voice_engine"] == "local" and info["voice_model"] == "small"
        assert info["local_stt_status"] == "ready" and info["local_stt_model"] == "small"
        resp = await transcribe(client, "ru")
        assert resp.status_code == 200 and resp.json() == {"text": "Привет из Whisper"}
        resp = await transcribe(client, "")
        assert resp.status_code == 200
    assert fake.calls == [{"language": "ru", "model": "small"}, {"language": "", "model": "small"}]
    async with app.state.db.sessionmaker() as db:
        rows = list(
            (await db.execute(select(UsageRecord).where(UsageRecord.source == "voice"))).scalars()
        )
    assert {(r.provider_kind, r.model, r.cost_usd) for r in rows} == {
        ("local", "small", Decimal(0))
    }


async def test_falls_back_to_the_provider_when_whisper_is_not_ready(
    app_factory: AppFactory,
) -> None:
    app = await owner_app(app_factory, stt_url="http://stt:8000", stt_health_cache_seconds=0)
    fake = FakeStt(status="missing")
    fake.install(app)
    async with logged_in_client(app) as client:
        resp = await transcribe(client)
        # configured but still downloading, and no provider: "try again later"
        assert resp.status_code == 503 and resp.json()["error"]["code"] == "voice_unavailable"
        await add_mock_model(client)
        info = (await client.get("/api/v1/ai/settings")).json()
        assert info["voice_engine"] == "provider" and info["local_stt_status"] == "missing"
        assert (await transcribe(client, "ru")).json() == {"text": "Привет, moloko"}
        # ready but failing: the provider answers instead
        fake.status, fake.fail = "ready", True
        assert (await transcribe(client, "ru")).json() == {"text": "Привет, moloko"}
    assert fake.calls == []


async def test_too_long_recordings_are_refused(app_factory: AppFactory) -> None:
    app = await owner_app(
        app_factory, voice_upload_max_bytes=10_000, transcription_provider_max_bytes=20_000
    )
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        resp = await client.post(
            "/api/v1/ai/transcribe",
            files={"audio": ("voice.webm", b"x" * 10_001, "audio/webm")},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 413 and resp.json()["error"]["code"] == "audio_too_large"

    # The provider's own cap applies only when the provider transcribes.
    app = await app_factory(voice_upload_max_bytes=100_000, transcription_provider_max_bytes=20_000)
    async with logged_in_client(app) as client:
        resp = await client.post(
            "/api/v1/ai/transcribe",
            files={"audio": ("voice.webm", b"x" * 30_000, "audio/webm")},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 413
