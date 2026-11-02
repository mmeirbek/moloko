"""Owner account management. Used by the CLI (there is no public registration) and by
the owner's own profile settings (``PATCH /auth/profile``)."""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, Conflict, NotFound
from app.core.security import MIN_PASSWORD_LENGTH, hash_password
from app.models.user import User
from app.repositories.sessions import SessionRepository
from app.repositories.users import UserRepository
from app.schemas.auth import USERNAME_PATTERN, ProfileField
from app.services.addressing import DISPLAY_NAME_MAX_CHARS, normalize_profile_text
from app.services.audit import ActorType, AuditService
from app.services.auth import normalize_username, utcnow

_USERNAME_RE = re.compile(USERNAME_PATTERN)

PROFILE_UPDATED = "user.profile_updated"


class InvalidInput(AppError):
    status_code = 422
    code = "validation_error"


def validate_username(username: str) -> str:
    normalized = normalize_username(username)
    if not _USERNAME_RE.fullmatch(normalized):
        raise InvalidInput(
            "Username must be 3-64 characters: a-z, 0-9, '.', '_' or '-', "
            "starting with a letter or digit."
        )
    return normalized


def validate_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise InvalidInput(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > 1024:
        raise InvalidInput("Password is too long.")
    return password


class UserService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.users = UserRepository(db)
        self.sessions = SessionRepository(db)
        self.audit = AuditService(db)

    async def create_owner(
        self, username: str, password: str, display_name: str | None = None
    ) -> User:
        """Create the single owner account. Refuses if any account already exists."""
        normalized = validate_username(username)
        validate_password(password)
        if await self.users.count() > 0:
            raise Conflict("An owner account already exists.")
        user = await self.users.add(
            User(
                username=normalized,
                password_hash=await asyncio.to_thread(hash_password, password),
                display_name=display_name,
            )
        )
        await self.audit.record(
            "user.created",
            "success",
            actor_type="system",
            user_id=user.id,
            resource_type="user",
            resource_id=str(user.id),
            details={"via": "cli"},
        )
        await self.db.commit()
        return user

    async def reset_password(self, username: str, new_password: str) -> User:
        """Set a new password and revoke every existing session of that user."""
        validate_password(new_password)
        user = await self.users.get_by_username(normalize_username(username))
        if user is None:
            raise NotFound("No such user.")
        user.password_hash = await asyncio.to_thread(hash_password, new_password)
        await self.sessions.revoke_all_for_user(user.id, utcnow())
        await self.audit.record(
            "user.password_reset",
            "success",
            actor_type="system",
            user_id=user.id,
            resource_type="user",
            resource_id=str(user.id),
            details={"via": "cli", "sessions_revoked": True},
        )
        await self.db.commit()
        return user

    # --- the owner's profile (form of address, display name) -------------------------

    async def update_profile(
        self,
        user: User,
        changes: dict[ProfileField, str | None],
        *,
        address_as_max_chars: int,
        actor_type: ActorType,
        actor_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        via: Literal["api", "cli"],
    ) -> list[str]:
        """Apply the given fields (each normalised; ``None``/blank = clear) and commit.

        A real change writes one ``user.profile_updated`` audit row with the old and new
        values (they are not secrets). Returns the names of the fields that changed.
        """
        limits: dict[ProfileField, int] = {
            "address_as": address_as_max_chars,
            "display_name": DISPLAY_NAME_MAX_CHARS,
        }
        values = {
            name: normalize_profile_text(value, field=name, max_chars=limits[name])
            for name, value in changes.items()
        }
        diff: dict[str, dict[str, str | None]] = {
            name: {"old": getattr(user, name), "new": value}
            for name, value in values.items()
            if getattr(user, name) != value
        }
        for name, change in diff.items():
            setattr(user, name, change["new"])
        changed = sorted(diff)
        if changed:
            await self.audit.record(
                PROFILE_UPDATED,
                "success",
                actor_type=actor_type,
                actor_id=actor_id,
                user_id=user.id,
                resource_type="user",
                resource_id=str(user.id),
                ip_address=ip_address,
                details={"via": via, "changed": changed, **diff},
            )
        await self.db.commit()
        return changed

    async def set_address_as(
        self, username: str, address_as: str | None, *, address_as_max_chars: int
    ) -> User:
        """CLI: set (or with ``None`` clear) how moloko addresses this user."""
        user = await self.users.get_by_username(normalize_username(username))
        if user is None:
            raise NotFound("No such user.")
        await self.update_profile(
            user,
            {"address_as": address_as},
            address_as_max_chars=address_as_max_chars,
            actor_type="system",
            via="cli",
        )
        return user
