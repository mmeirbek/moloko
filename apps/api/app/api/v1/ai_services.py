from __future__ import annotations

import uuid

from fastapi import APIRouter, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentAuth, DbSession, GatewayDep, SettingsDep
from app.core.config import Settings
from app.core.errors import AppError
from app.providers.gateway import ModelGateway
from app.schemas.ai_services import AiServicesIn, AiServicesOut, Transcript
from app.services import ai_services
from app.services.audit import AuditService

router = APIRouter(prefix="/ai", tags=["voice & search"])


class AudioTooLarge(AppError):
    status_code = 413
    code = "audio_too_large"
    message = "The recording is too long."


async def _out(
    db: AsyncSession, gateway: ModelGateway, settings: Settings, user_id: uuid.UUID
) -> AiServicesOut:
    chosen = await ai_services.load_settings(db, user_id)
    try:
        target = await ai_services.resolve(db, gateway, settings, user_id)
    except ai_services.AiServiceUnavailable:
        target = None
    return AiServicesOut(
        provider_id=chosen.get("provider_id"),
        active_provider_id=target.provider_id if target else None,
        active_provider_name=target.name if target else None,
        available=target is not None,
        transcription_model=chosen.get("transcription_model") or settings.transcription_model,
        embedding_model=chosen.get("embedding_model") or settings.embedding_model,
        embedding_dimensions=int(
            chosen.get("embedding_dimensions") or settings.embedding_dimensions
        ),
        semantic_search=bool(chosen.get("semantic_search", True)),
    )


@router.get("/settings", response_model=AiServicesOut, summary="Voice input and semantic search")
async def get_settings(
    ctx: CurrentAuth, db: DbSession, gateway: GatewayDep, settings: SettingsDep
) -> AiServicesOut:
    return await _out(db, gateway, settings, ctx.user.id)


@router.put("/settings", response_model=AiServicesOut)
async def put_settings(
    body: AiServicesIn, ctx: CurrentAuth, db: DbSession, gateway: GatewayDep, settings: SettingsDep
) -> AiServicesOut:
    value = body.model_dump(mode="json", exclude_none=True)
    value.setdefault("semantic_search", body.semantic_search)
    await ai_services.save_settings(db, ctx.user.id, value)
    await AuditService(db).record(
        "ai_services.updated",
        "success",
        actor_type="user",
        actor_id=ctx.user.id,
        user_id=ctx.user.id,
        resource_type="ai_services",
        details={k: v for k, v in value.items() if k != "provider_id"},
    )
    await db.commit()
    return await _out(db, gateway, settings, ctx.user.id)


@router.post("/transcribe", response_model=Transcript, summary="Speech to text (voice input)")
async def transcribe(
    audio: UploadFile,
    ctx: CurrentAuth,
    db: DbSession,
    gateway: GatewayDep,
    settings: SettingsDep,
    language: str | None = Form(default=None, max_length=8),
) -> Transcript:
    data = await audio.read(settings.voice_max_bytes + 1)
    if len(data) > settings.voice_max_bytes:
        raise AudioTooLarge(details={"max_bytes": settings.voice_max_bytes})
    text = await ai_services.transcribe(
        db,
        gateway,
        settings,
        ctx.user.id,
        data,
        (audio.filename or "voice.webm")[:100],
        (language or "")[:2] or None,
    )
    return Transcript(text=text)
