from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentAuth, SettingsDep
from app.codex.client import CodexClient

router = APIRouter(prefix="/codex", tags=["models"])

LOGIN_COMMAND = "docker compose exec codex codex login --device-auth"


class CodexStatusOut(BaseModel):
    """Codex with the owner's ChatGPT sign-in (service `codex`)."""

    configured: bool = Field(description="CODEX_URL is set (the codex service is part of moloko)")
    reachable: bool
    logged_in: bool
    mode: str | None = Field(description='"chatgpt" or "api_key" — how Codex is signed in')
    version: str
    login_command: str = Field(description="What the owner runs on the server to sign in")


@router.get(
    "/status",
    response_model=CodexStatusOut,
    summary="Whether Codex is signed in with ChatGPT on the server",
)
async def codex_status(ctx: CurrentAuth, settings: SettingsDep) -> CodexStatusOut:
    s = await CodexClient(settings).status()
    return CodexStatusOut(
        configured=s.configured,
        reachable=s.reachable,
        logged_in=s.logged_in,
        mode=s.mode,
        version=s.version,
        login_command=LOGIN_COMMAND,
    )
