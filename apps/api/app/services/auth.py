"""Owner authentication: login, logout, session validation and the owner's own
session lifetime (spec section 20)."""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import (
    AppError,
    InvalidCredentials,
    InvalidPassword,
    NotAuthenticated,
    TooManyAttempts,
)
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
# A signed-in user confirming a sensitive change with their password.
CONFIRM_FAILED = "auth.password_confirm_failed"
CONFIRM_BLOCKED = "auth.password_confirm_blocked"
SESSION_TTL_CHANGED = "auth.session_ttl_changed"
# Passkeys (app.services.passkeys): adding and deleting one is confirmed with the password.
PASSKEY_ADDED = "auth.passkey_added"
PASSKEY_DELETED = "auth.passkey_deleted"

# Every wrong password — at login or when confirming a change — and every failed passkey
# sign-in counts toward the same per-username lockout, so no endpoint can be used to guess
# the password, and a locked account cannot be entered with a passkey either.
PASSWORD_FAILURE_ACTIONS = (LOGIN_FAILED, CONFIRM_FAILED)
# A correct password (or a passkey sign-in) restarts the count (these entries carry the
# same subject_key).
PASSWORD_SUCCESS_ACTIONS = (LOGIN_OK, SESSION_TTL_CHANGED, PASSKEY_ADDED, PASSKEY_DELETED)

LoginMethod = Literal["password", "passkey"]


class SessionTtlOutOfRange(AppError):
    status_code = 422
    code = "session_ttl_out_of_range"
    message = "The session lifetime is outside the allowed range."


def utcnow() -> datetime:
    return datetime.now(UTC)


def normalize_username(username: str) -> str:
    return username.strip().lower()


def effective_session_ttl_hours(settings: Settings, chosen_hours: int | None) -> int:
    """How long a sign-in lasts: the user's own choice (``users.session_ttl_hours``),
    kept within the configured bounds (they may have been narrowed since), or the
    configured default when there is none."""
    if chosen_hours is None:
        return settings.session_ttl_hours
    return max(settings.session_ttl_min_hours, min(chosen_hours, settings.session_ttl_max_hours))


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
    ttl_seconds: int  # the session's lifetime = the cookie's max-age


@dataclass(frozen=True)
class SessionSettings:
    ttl_hours: int  # effective lifetime of this user's sign-ins
    default_ttl_hours: int
    min_hours: int
    max_hours: int
    uses_default: bool  # no own choice stored: follows SESSION_TTL_HOURS
    current_session_expires_at: datetime


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
        normalized = normalize_username(username)
        subject_key = login_subject_key(normalized)

        await self.enforce_lockout(subject_key, client)

        user = await self.users.get_by_username(normalized)
        if user is None or not user.is_active:
            await asyncio.to_thread(burn_password_check, password)
            await self.record_failure(
                subject_key, client, reason="unknown_or_inactive", method="password"
            )
            raise InvalidCredentials()

        if not await asyncio.to_thread(verify_password, user.password_hash, password):
            await self.record_failure(
                subject_key, client, reason="bad_password", user=user, method="password"
            )
            raise InvalidCredentials()

        if password_needs_rehash(user.password_hash):
            user.password_hash = await asyncio.to_thread(hash_password, password)

        return await self.start_session(user, client, subject_key=subject_key, method="password")

    async def start_session(
        self,
        user: User,
        client: ClientInfo,
        *,
        subject_key: str,
        method: LoginMethod,
        details: dict[str, Any] | None = None,
    ) -> LoginResult:
        """Sign ``user`` in after a successful password or passkey check: a new server-side
        session with the user's own lifetime, audited as ``auth.login`` (which also restarts
        the lockout count). Commits."""
        now = utcnow()
        ttl = timedelta(hours=effective_session_ttl_hours(self.settings, user.session_ttl_hours))
        token = generate_session_token()
        session = await self.sessions.add(
            Session(
                user_id=user.id,
                token_hash=hash_token(token),
                expires_at=now + ttl,
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
            details={"subject_key": subject_key, "method": method, **(details or {})},
        )
        await self.db.commit()
        logger.info(
            "login_ok",
            extra={"user_id": str(user.id), "session_id": str(session.id), "method": method},
        )
        return LoginResult(
            user=user, session=session, token=token, ttl_seconds=int(ttl.total_seconds())
        )

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

    # --- the owner's own session lifetime (Settings → Security) --------------------

    def session_settings(self, ctx: AuthContext) -> SessionSettings:
        return self._session_settings(ctx.user.session_ttl_hours, ctx.session.expires_at)

    async def change_session_ttl(
        self, ctx: AuthContext, ttl_hours: int | None, password: str, client: ClientInfo
    ) -> SessionSettings:
        """Set the user's own sign-in lifetime (``None`` = back to the default).

        Confirmed with the password; wrong passwords count toward the login lockout.
        The current session then lasts the new lifetime from now; the user's other
        sessions are only ever shortened to it (never extended, nobody is signed out).
        """
        s = self.settings
        if ttl_hours is not None and not (
            s.session_ttl_min_hours <= ttl_hours <= s.session_ttl_max_hours
        ):
            raise SessionTtlOutOfRange(
                details={
                    "field": "ttl_hours",
                    "min": s.session_ttl_min_hours,
                    "max": s.session_ttl_max_hours,
                }
            )

        user = ctx.user
        subject_key = await self.confirm_password(user, password, client, purpose="session_ttl")

        old_hours = effective_session_ttl_hours(s, user.session_ttl_hours)
        new_hours = effective_session_ttl_hours(s, ttl_hours)
        expires_at = utcnow() + timedelta(hours=new_hours)
        await self.users.set_session_ttl_hours(user.id, ttl_hours)
        await self.sessions.set_expiry(ctx.session.id, expires_at)
        shortened = await self.sessions.cap_expiry_for_user(
            user.id, expires_at, except_session_id=ctx.session.id
        )
        await self.audit.record(
            SESSION_TTL_CHANGED,
            "success",
            actor_type="user",
            actor_id=user.id,
            user_id=user.id,
            resource_type="user",
            resource_id=str(user.id),
            ip_address=client.ip_address,
            details={
                "subject_key": subject_key,
                "old_hours": old_hours,
                "new_hours": new_hours,
                "uses_default": ttl_hours is None,
                "other_sessions_shortened": shortened,
            },
        )
        await self.db.commit()
        logger.info(
            "session_ttl_changed",
            extra={"user_id": str(user.id), "hours": new_hours, "shortened": shortened},
        )
        return self._session_settings(ttl_hours, expires_at)

    async def csrf_cookie_max_age(self, session_token: str | None) -> int:
        """The CSRF cookie lives as long as the session it is bound to; without a valid
        session, as long as a new sign-in would by default."""
        if session_token:
            session = await self.sessions.get_by_token_hash(hash_token(session_token))
            now = utcnow()
            if (
                session is not None
                and session.revoked_at is None
                and session.expires_at > now
                and session.user.is_active
            ):
                return max(1, math.ceil((session.expires_at - now).total_seconds()))
        return effective_session_ttl_hours(self.settings, None) * 3600

    async def confirm_password(
        self, user: User, password: str, client: ClientInfo, *, purpose: str
    ) -> str:
        """Check the signed-in user's password before a sensitive change.

        Subject to the login lockout (429), and a wrong password counts toward it (403
        ``invalid_password``, never 401: the session itself is fine). Returns the user's
        lockout ``subject_key`` for the success audit entry that restarts the count.
        """
        subject_key = login_subject_key(user.username)
        await self.enforce_lockout(subject_key, client, action=CONFIRM_BLOCKED, actor=user)
        if not await asyncio.to_thread(verify_password, user.password_hash, password):
            await self.record_failure(
                subject_key,
                client,
                reason="bad_password",
                user=user,
                action=CONFIRM_FAILED,
                actor=user,
                purpose=purpose,
            )
            raise InvalidPassword()
        return subject_key

    async def enforce_lockout(
        self,
        subject_key: str,
        client: ClientInfo,
        *,
        action: str = LOGIN_BLOCKED,
        actor: User | None = None,
    ) -> None:
        last_ok = await self.audit_logs.last_time(
            actions=PASSWORD_SUCCESS_ACTIONS, subject_key=subject_key
        )
        failures = await self.audit_logs.count_recent(
            actions=PASSWORD_FAILURE_ACTIONS,
            subject_key=subject_key,
            window_seconds=self.settings.login_lockout_seconds,
            after=last_ok,  # failures before the last correct password don't count
        )
        if failures >= self.settings.login_max_failures:
            await self.audit.record(
                action,
                "denied",
                actor_type="user" if actor else "anonymous",
                actor_id=actor.id if actor else None,
                user_id=actor.id if actor else None,
                ip_address=client.ip_address,
                details={"subject_key": subject_key, "failures": failures},
            )
            await self.db.commit()
            raise TooManyAttempts(headers={"Retry-After": str(self.settings.login_lockout_seconds)})

    async def record_failure(
        self,
        subject_key: str,
        client: ClientInfo,
        *,
        reason: str,
        user: User | None = None,
        action: str = LOGIN_FAILED,
        actor: User | None = None,
        purpose: str | None = None,
        method: LoginMethod | None = None,
    ) -> None:
        """``user``: whose password (or passkey) it was, if known; ``actor``: who was
        signed in. Commits, so the failure counts even if the request then fails."""
        details = {"subject_key": subject_key, "reason": reason}
        if purpose:
            details["purpose"] = purpose
        if method:
            details["method"] = method
        await self.audit.record(
            action,
            "failure",
            actor_type="user" if actor else "anonymous",
            actor_id=actor.id if actor else None,
            user_id=user.id if user else None,
            ip_address=client.ip_address,
            details=details,
        )
        await self.db.commit()
        logger.warning(action.removeprefix("auth."), extra={"reason": reason})

    # --- internals -------------------------------------------------------------

    def _session_settings(
        self, chosen_hours: int | None, current_expires_at: datetime
    ) -> SessionSettings:
        s = self.settings
        return SessionSettings(
            ttl_hours=effective_session_ttl_hours(s, chosen_hours),
            default_ttl_hours=s.session_ttl_hours,
            min_hours=s.session_ttl_min_hours,
            max_hours=s.session_ttl_max_hours,
            uses_default=chosen_hours is None,
            current_session_expires_at=current_expires_at,
        )
