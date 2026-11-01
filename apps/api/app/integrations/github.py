"""GitHub REST API client (spec 15.6). Fine-grained personal access token, stored
encrypted; the API host is pinned (an environment variable can't redirect the token)."""

from __future__ import annotations

import base64
import contextlib
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.crypto import DecryptionFailed, EncryptionUnavailable, secret_box
from app.models.tooling import Integration

API = "https://api.github.com"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
BRANCH_RE = re.compile(r"^(?!/)(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}(?<!/)(?<!\.lock)$")

TRANSPORT: httpx2.AsyncBaseTransport | None = None  # tests


class GitHubError(Exception):
    """A user-facing GitHub problem (safe to show; never contains the token)."""


@dataclass
class GitHubAccess:
    token: str
    allowed_repos: list[str] = field(default_factory=list)

    def repo_allowed(self, repo: str) -> bool:
        return not self.allowed_repos or repo.lower() in {r.lower() for r in self.allowed_repos}


async def load_integration(db: AsyncSession, user_id: uuid.UUID) -> Integration | None:
    return (
        await db.execute(
            select(Integration).where(Integration.user_id == user_id, Integration.kind == "github")
        )
    ).scalar_one_or_none()


async def access_for(
    db: AsyncSession, settings: Settings, user_id: uuid.UUID
) -> GitHubAccess | None:
    row = await load_integration(db, user_id)
    if row is None or not row.enabled or not row.secret_encrypted:
        return None
    try:
        token = secret_box(settings).decrypt(row.secret_encrypted)
    except (EncryptionUnavailable, DecryptionFailed):
        return None
    return GitHubAccess(token=token, allowed_repos=list(row.config.get("allowed_repos") or []))


async def call(
    settings: Settings,
    token: str,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: Any = None,
) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {token}",
        "User-Agent": "moloko",
    }
    try:
        async with httpx2.AsyncClient(
            base_url=API, transport=TRANSPORT, timeout=settings.integration_timeout_seconds
        ) as client:
            resp = await client.request(method, path, params=params, json=json, headers=headers)
    except httpx2.HTTPError:
        raise GitHubError("GitHub cannot be reached right now.") from None
    if resp.status_code == 401:
        raise GitHubError("GitHub rejected the token. Check it in Integrations.")
    if resp.status_code == 403:
        if resp.headers.get("x-ratelimit-remaining") == "0":
            raise GitHubError("GitHub rate limit reached. Try again later.")
        raise GitHubError("The token is not allowed to do this (check its permissions).")
    if resp.status_code == 404:
        raise GitHubError("Not found on GitHub (or the token cannot see it).")
    if resp.status_code == 409:
        raise GitHubError("GitHub reported a conflict (for example, the branch changed).")
    if resp.status_code == 422:
        message = ""
        with contextlib.suppress(ValueError):
            message = str(resp.json().get("message", ""))[:200]
        raise GitHubError(f"GitHub refused the request: {message or 'validation failed'}.")
    if resp.status_code >= 400:
        raise GitHubError(f"GitHub answered HTTP {resp.status_code}.")
    return resp.json() if resp.content else None


async def whoami(settings: Settings, token: str) -> str:
    data = await call(settings, token, "GET", "/user")
    return str(data.get("login", ""))


async def default_branch(settings: Settings, token: str, repo: str) -> str:
    data = await call(settings, token, "GET", f"/repos/{repo}")
    return str(data.get("default_branch") or "main")


def decode_content(item: dict[str, Any]) -> str:
    raw = base64.b64decode(item.get("content") or "")
    if b"\x00" in raw[:8192]:
        raise GitHubError("This looks like a binary file.")
    return raw.decode("utf-8", "replace")
