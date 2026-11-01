"""Voice input: speech to text through the owner's OpenAI-type provider."""

from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import select

from app.models import UsageRecord, User
from tests.conftest import AppFactory, add_mock_model, csrf_headers, logged_in_client


async def test_voice_needs_a_capable_provider_then_transcribes(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        resp = await client.post(
            "/api/v1/ai/transcribe",
            files={"audio": ("voice.webm", b"\x1aE\xdf\xa3 fake", "audio/webm")},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 409 and resp.json()["error"]["code"] == "ai_service_unavailable"
        assert (await client.get("/api/v1/ai/settings")).json()["available"] is False

        await add_mock_model(client)
        info = (await client.get("/api/v1/ai/settings")).json()
        assert info["available"] is True and info["transcription_model"]
        resp = await client.post(
            "/api/v1/ai/transcribe",
            files={"audio": ("voice.webm", b"\x1aE\xdf\xa3 fake", "audio/webm")},
            data={"language": "ru"},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"text": "Привет, moloko"}

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
        assert [r.model for r in rows] == [info["transcription_model"]]


async def test_too_long_recordings_are_refused(app_factory: AppFactory) -> None:
    from app.services.users import UserService
    from tests.conftest import OWNER_PASSWORD, OWNER_USERNAME

    app = await app_factory(voice_max_bytes=10_000)
    async with app.state.db.sessionmaker() as db:
        await UserService(db).create_owner(OWNER_USERNAME, OWNER_PASSWORD, "Owner")
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        resp = await client.post(
            "/api/v1/ai/transcribe",
            files={"audio": ("voice.webm", b"x" * 10_001, "audio/webm")},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 413 and resp.json()["error"]["code"] == "audio_too_large"
