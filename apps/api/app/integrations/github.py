"""GitHub REST API client (spec 15.6). Fine-grained personal access token, stored
encrypted; the API host is pinned (an environment variable can't redirect the token)."""

from __future__ import annotations

import base64
import contextlib
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.crypto import DecryptionFailed, EncryptionUnavailable, secret_box
from app.models.tooling import Integration

API = "https://api.github.com"
ARCHIVE_HOSTS = frozenset({"codeload.github.com"})  # where /tarball redirects to
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


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {token}",
        "User-Agent": "moloko",
    }


async def call(
    settings: Settings,
    token: str,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: Any = None,
    missing_ok: bool = False,  # 404 → None (e.g. "does this branch exist?")
) -> Any:
    try:
        async with httpx2.AsyncClient(
            base_url=API, transport=TRANSPORT, timeout=settings.integration_timeout_seconds
        ) as client:
            resp = await client.request(
                method, path, params=params, json=json, headers=_headers(token)
            )
    except httpx2.HTTPError:
        raise GitHubError("GitHub cannot be reached right now.") from None
    if resp.status_code == 404 and missing_ok:
        return None
    raise_for(resp)
    return resp.json() if resp.content else None


def raise_for(resp: httpx2.Response) -> None:
    """A safe, user-facing GitHubError for an error answer (never the token or URL)."""
    if resp.status_code < 400:
        return
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
    raise GitHubError(f"GitHub answered HTTP {resp.status_code}.")


async def download_archive(
    settings: Settings, token: str, repo: str, ref: str, dest: Path, max_bytes: int
) -> None:
    """The repository at ``ref`` as a .tar.gz, streamed into ``dest`` (at most ``max_bytes``).

    GitHub answers with a redirect to codeload.github.com whose URL carries a short-lived
    token for private repositories. The redirect is followed only to that host, without our
    token, and the URL is never logged or shown."""
    try:
        async with httpx2.AsyncClient(
            base_url=API, transport=TRANSPORT, timeout=settings.integration_timeout_seconds
        ) as client:
            resp = await client.get(f"/repos/{repo}/tarball/{ref}", headers=_headers(token))
            raise_for(resp)
            location = resp.headers.get("location", "")
            parts = urlsplit(location)
            if resp.status_code not in (301, 302, 303, 307, 308) or not (
                parts.scheme == "https" and parts.hostname in ARCHIVE_HOSTS
            ):
                raise GitHubError("GitHub did not offer the repository archive.")
            async with client.stream(
                "GET", location, headers={"User-Agent": "moloko"}, follow_redirects=False
            ) as archive:
                raise_for(archive)
                if archive.status_code != 200:
                    raise GitHubError(f"GitHub answered HTTP {archive.status_code}.")
                size = 0
                with dest.open("wb") as fh:
                    async for chunk in archive.aiter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise GitHubError(
                                f"The repository archive is larger than {max_bytes} bytes "
                                "(GITHUB_CHECKOUT_MAX_BYTES)."
                            )
                        fh.write(chunk)
    except httpx2.HTTPError:
        raise GitHubError("GitHub cannot be reached right now.") from None


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
