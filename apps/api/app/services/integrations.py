"""GitHub connection settings and the status of tools' back-ends (sandbox, search)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.crypto import secret_box, secret_hint
from app.events import bus
from app.integrations import github as gh
from app.models.tooling import Integration
from app.sandbox.base import Sandbox
from app.schemas.tooling import (
    GitHubIntegrationOut,
    GitHubIntegrationUpdate,
    IntegrationsStatus,
    SandboxStatus,
)
from app.services.audit import AuditService


def github_out(row: Integration | None) -> GitHubIntegrationOut:
    if row is None:
        return GitHubIntegrationOut(
            connected=False,
            enabled=False,
            token_hint=None,
            login=None,
            allowed_repos=[],
            status="unknown",
            last_error=None,
            last_checked_at=None,
        )
    return GitHubIntegrationOut(
        connected=bool(row.secret_encrypted),
        enabled=row.enabled,
        token_hint=row.secret_hint,
        login=row.config.get("login"),
        allowed_repos=list(row.config.get("allowed_repos") or []),
        status=row.status,
        last_error=row.last_error,
        last_checked_at=row.last_checked_at,
    )


class IntegrationService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db, self.settings = db, settings

    async def github(self, user_id: uuid.UUID) -> GitHubIntegrationOut:
        return github_out(await gh.load_integration(self.db, user_id))

    async def update_github(
        self, user_id: uuid.UUID, data: GitHubIntegrationUpdate
    ) -> GitHubIntegrationOut:
        row = await gh.load_integration(self.db, user_id)
        if row is None:
            row = Integration(
                user_id=user_id, kind="github", config={}, enabled=True, status="unknown"
            )
            self.db.add(row)
        changed: list[str] = []
        if data.clear_token and row.secret_encrypted:
            row.secret_encrypted = row.secret_hint = None
            row.config = {**row.config, "login": None}
            row.status = "unknown"
            changed.append("token_cleared")
        if data.token is not None:
            token = data.token.get_secret_value().strip()
            row.secret_encrypted = secret_box(self.settings).encrypt(token)
            row.secret_hint = secret_hint(token)
            changed.append("token")
        if data.enabled is not None and data.enabled != row.enabled:
            row.enabled = data.enabled
            changed.append("enabled")
        if data.allowed_repos is not None:
            row.config = {**row.config, "allowed_repos": data.allowed_repos}
            changed.append("allowed_repos")
        if data.token is not None:
            await self._check(row, data.token.get_secret_value().strip())
        await AuditService(self.db).record(
            "integration.updated",
            "success",
            actor_type="user",
            actor_id=user_id,
            user_id=user_id,
            resource_type="integration",
            resource_id="github",
            details={"changed": changed},
        )
        await bus.commit(self.db)
        return github_out(row)

    async def test_github(self, user_id: uuid.UUID) -> GitHubIntegrationOut:
        row = await gh.load_integration(self.db, user_id)
        access = await gh.access_for(self.db, self.settings, user_id)
        if row is None or access is None:
            return github_out(row)
        await self._check(row, access.token)
        await bus.commit(self.db)
        return github_out(row)

    async def _check(self, row: Integration, token: str) -> None:
        row.last_checked_at = datetime.now(UTC)
        try:
            login = await gh.whoami(self.settings, token)
        except gh.GitHubError as exc:
            row.status, row.last_error = "error", str(exc)[:500]
            return
        row.status, row.last_error = "ok", None
        row.config = {**row.config, "login": login}

    async def status(self, user_id: uuid.UUID, sandbox: Sandbox | None) -> IntegrationsStatus:
        health: dict[str, object] = await sandbox.health() if sandbox is not None else {}
        limits = health.get("limits")
        return IntegrationsStatus(
            sandbox=SandboxStatus(
                configured=sandbox is not None,
                ok=bool(health.get("ok")),
                image=str(health["image"]) if health.get("image") else None,
                limits=limits if isinstance(limits, dict) else {},
                network=str(health.get("network") or "none"),
                allowed_commands=self.settings.sandbox_allowed_commands,
            ),
            web_search=bool(self.settings.searxng_url),
            github=await self.github(user_id),
        )
