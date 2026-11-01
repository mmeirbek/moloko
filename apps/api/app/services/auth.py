"""Owner authentication: login, logout and session validation (spec section 20)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import InvalidCredentials, NotAuthenticated, TooManyAttempts
from app.core.security import (
    burn_password_check,
    generate_session_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    verify_password,
)
from app.models.session import Session
from app.models.user import User
from app.repositories.audit_logs import AuditLogRepository
from app.repositories.sessions import SessionRepository
from app.repositories.users import UserRepository
from app.services.audit import AuditService

logger = logging.getLogger("moloko.auth")

LOGIN_OK = "auth.login"
LOGIN_FAILED = "auth.login_failed"
LOGIN_BLOCKED = "auth.login_blocked"
LOGOUT = "auth.logout"


def utcnow() -> datetime:
    return datetime.now(UTC)


def normalize_username(username: str) -> str:
    return username.strip().lower()


def login_subject_key(username: str) -> str:
    """Stable, non-reversible key for per-username lockout bookkeeping.

    We never store the raw submitted username for failed logins: people sometimes
    type their password into the username field.
    """
    return hash_token(f"login:{normalize_username(username)}")


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: Session


@dataclass(frozen=True)
class LoginResult:
    user: User
    session: Session
    token: str  # raw session token — goes into the cookie, never into logs or the DB


@dataclass(frozen=True)
class ClientInfo:
    ip_address: str | None = None
    user_agent: str | None = None


class AuthService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.users = UserRepository(db)
        self.sessions = SessionRepository(db)
        self.audit_logs = AuditLogRepository(db)
        self.audit = AuditService(db)

    async def login(self, username: str, password: str, client: ClientInfo) -> LoginResult:
        now = utcnow()
        normalized = normalize_username(username)
        subject_key = login_subject_key(normalized)

        await self._enforce_lockout(subject_key, now, client)

        user = await self.users.get_by_username(normalized)
        if user is None or not user.is_active:
            await asyncio.to_thread(burn_password_check, password)
            await self._record_failure(subject_key, client, reason="unknown_or_inactive")
            raise InvalidCredentials()

        if not await asyncio.to_thread(verify_password, user.password_hash, password):
            await self._record_failure(subject_key, client, reason="bad_password", user=user)
            raise InvalidCredentials()

        if password_needs_rehash(user.password_hash):
            user.password_hash = await asyncio.to_thread(hash_password, password)

        token = generate_session_token()
        session = await self.sessions.add(
            Session(
                user_id=user.id,
                token_hash=hash_token(token),
                expires_at=now + timedelta(hours=self.settings.session_ttl_hours),
                last_seen_at=now,
                ip_address=client.ip_address,
                user_agent=(client.user_agent or "")[:512] or None,
            )
        )
        user.last_login_at = now
        await self.audit.record(
            LOGIN_OK,
            "success",
            actor_type="user",
            actor_id=user.id,
            user_id=user.id,
            resource_type="session",
            resource_id=str(session.id),
            ip_address=client.ip_address,
            details={"subject_key": subject_key},
        )
        await self.db.commit()
        logger.info("login_ok", extra={"user_id": str(user.id), "session_id": str(session.id)})
        return LoginResult(user=user, session=session, token=token)

    async def authenticate(self, token: str | None) -> AuthContext:
        if not token:
            raise NotAuthenticated()
        session = await self.sessions.get_by_token_hash(hash_token(token))
        now = utcnow()
        if (
            session is None
            or session.revoked_at is not None
            or session.expires_at <= now
            or not session.user.is_active
        ):
            raise NotAuthenticated()

        interval = timedelta(seconds=self.settings.session_touch_interval_seconds)
        if now - session.last_seen_at >= interval:
            session.last_seen_at = now
            await self.db.commit()
        return AuthContext(user=session.user, session=session)

    async def logout(self, ctx: AuthContext, client: ClientInfo) -> None:
        await self.sessions.revoke(ctx.session.id, utcnow())
        await self.audit.record(
            LOGOUT,
            "success",
            actor_type="user",
            actor_id=ctx.user.id,
            user_id=ctx.user.id,
            resource_type="session",
            resource_id=str(ctx.session.id),
            ip_address=client.ip_address,
        )
        await self.db.commit()

    # --- internals -------------------------------------------------------------

    async def _enforce_lockout(self, subject_key: str, now: datetime, client: ClientInfo) -> None:
        window = timedelta(seconds=self.settings.login_lockout_seconds)
        since = now - window
        last_ok = await self.audit_logs.last_time(action=LOGIN_OK, subject_key=subject_key)
        if last_ok is not None and last_ok > since:
            since = last_ok  # failures before the last successful login don't count
        failures = await self.audit_logs.count_since(
            action=LOGIN_FAILED, subject_key=subject_key, since=since
        )
        if failures >= self.settings.login_max_failures:
            await self.audit.record(
                LOGIN_BLOCKED,
                "denied",
                actor_type="anonymous",
                ip_address=client.ip_address,
                details={"subject_key": subject_key, "failures": failures},
            )
            await self.db.commit()
            raise TooManyAttempts(headers={"Retry-After": str(self.settings.login_lockout_seconds)})

    async def _record_failure(
        self, subject_key: str, client: ClientInfo, *, reason: str, user: User | None = None
    ) -> None:
        await self.audit.record(
            LOGIN_FAILED,
            "failure",
            actor_type="anonymous",
            user_id=user.id if user else None,
            ip_address=client.ip_address,
            details={"subject_key": subject_key, "reason": reason},
        )
        await self.db.commit()
        logger.warning("login_failed", extra={"reason": reason})
