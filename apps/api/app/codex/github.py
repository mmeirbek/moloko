"""The owner's GitHub access for Codex (owner, 2026-11-05: let moloko use my GitHub account
boldly on my behalf): the token saved in Settings → Integrations →
GitHub goes to the codex service, so Codex's git and gh act as the owner. Sent when the owner
saves it and at startup; never logged."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.codex.client import CodexClient
from app.core.config import Settings
from app.integrations import github as gh
from app.providers.base import ProviderError

logger = logging.getLogger("moloko.codex")


async def sync_github(db: AsyncSession, settings: Settings, user_id: uuid.UUID) -> None:
    client = CodexClient(settings)
    if not client.configured:
        return
    access = await gh.access_for(db, settings, user_id)
    row = await gh.load_integration(db, user_id) if access else None
    login = str((row.config or {}).get("login") or "") if row else ""
    try:
        await client.set_github(access.token if access else None, login or None)
    except ProviderError as exc:
        logger.warning("codex_github_sync_failed", extra={"kind": exc.kind})
