"""Owner account management. Used by the CLI (there is no public registration)."""

from __future__ import annotations

import asyncio
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, Conflict, NotFound
from app.core.security import MIN_PASSWORD_LENGTH, hash_password
from app.models.user import User
from app.repositories.sessions import SessionRepository
from app.repositories.users import UserRepository
from app.schemas.auth import USERNAME_PATTERN
from app.services.audit import AuditService
from app.services.auth import normalize_username, utcnow

_USERNAME_RE = re.compile(USERNAME_PATTERN)


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
