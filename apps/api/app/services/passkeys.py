"""Passkeys (WebAuthn): sign in with Face ID / Touch ID instead of the password.

* Verification is done by ``py_webauthn`` (Duo Labs); this module adds the policy around it.
* Passkeys are off unless ``WEBAUTHN_RP_ID`` and ``WEBAUTHN_ORIGINS`` are set (WebAuthn needs
  a real domain, e.g. the server's ``*.ts.net`` name); the password always keeps working.
* Adding a passkey needs a signed-in owner *and* the current password (same lockout as every
  other password check). Deleting one needs the password too, so a borrowed or stolen session
  can neither add a way in nor take the owner's away. Renaming needs only the session.
* Challenges are random, single-use and short-lived: kept in Valkey with a TTL (ephemeral by
  design — losing one only means starting the prompt again) and taken with GETDEL, so a
  replayed response finds nothing. A registration challenge is bound to the session that
  asked for it; a sign-in challenge to the browser that asked (an HttpOnly cookie).
* Every passkey sign-in requires user verification (Face ID / Touch ID / device PIN), not
  just presence. A successful one creates a normal session exactly like the password login
  (``AuthService.start_session``: audit ``auth.login`` with ``method: passkey``); every
  failed one for a known passkey counts toward the owner's login lockout, and a locked
  account cannot be entered with a passkey either.
* Never logged or audited: credential ids, public keys, challenges, client data, signatures.
  The audit log names a passkey by our own row id and its name.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import (
    options_to_json_dict,
    parse_authentication_credential_json,
    parse_client_data_json,
    parse_registration_credential_json,
)
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticationCredential,
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    PublicKeyCredentialHint,
    RegistrationCredential,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.core.config import Settings
from app.core.errors import AppError, NotFound
from app.core.security import hash_token
from app.models.passkey import PASSKEY_NAME_MAX_CHARS, WebAuthnCredential
from app.models.user import User
from app.repositories.passkeys import PasskeyRepository
from app.services.addressing import normalize_profile_text
from app.services.audit import AuditService
from app.services.auth import (
    PASSKEY_ADDED,
    PASSKEY_DELETED,
    AuthContext,
    AuthService,
    ClientInfo,
    LoginResult,
    login_subject_key,
)

logger = logging.getLogger("moloko.passkeys")

PASSKEY_ADD_FAILED = "auth.passkey_add_failed"
PASSKEY_RENAMED = "auth.passkey_renamed"

# Failed sign-ins with a passkey nobody registered can't be tied to an account; they are
# audited under one shared key that no account's lockout reads.
UNKNOWN_PASSKEY_SUBJECT = hash_token("passkey:unknown-credential")
DEFAULT_PASSKEY_NAME = "Passkey"
_KNOWN_TRANSPORTS = frozenset(t.value for t in AuthenticatorTransport)
_CHALLENGE_PREFIX = "webauthn:challenge:"

Purpose = Literal["register", "login"]


# --- errors ----------------------------------------------------------------------------


class PasskeysDisabled(AppError):
    status_code = 404
    code = "passkeys_disabled"
    message = "Passkeys are not set up on this server (WEBAUTHN_RP_ID / WEBAUTHN_ORIGINS)."


class PasskeyRejected(AppError):
    """Sign-in with a passkey failed. One message for every reason (unknown passkey, bad
    signature, wrong site…), so the response tells an attacker nothing."""

    status_code = 401
    code = "passkey_rejected"
    message = "The passkey could not be verified."


class PasskeyExpired(AppError):
    """The prompt's challenge is gone: too old, already used, or from another browser.
    401 at sign-in; 400 when adding a passkey (the session itself is fine)."""

    status_code = 401
    code = "passkey_expired"
    message = "The passkey prompt has expired. Try again."


class PasskeyInvalid(AppError):
    status_code = 400
    code = "passkey_invalid"
    message = "The new passkey could not be verified."


class PasskeyLimitReached(AppError):
    status_code = 409
    code = "passkey_limit_reached"
    message = "Too many passkeys. Delete one you no longer use first."


class PasskeyAlreadyRegistered(AppError):
    status_code = 409
    code = "passkey_already_registered"
    message = "This passkey is already added."


# --- challenges (Valkey) ----------------------------------------------------------------------


@dataclass(frozen=True)
class PendingChallenge:
    purpose: Purpose
    binding: str  # registration: the session id; sign-in: hash of the browser's flow cookie
    user_id: str | None


def _challenge_key(challenge: bytes) -> str:
    # The key is a hash: the challenge itself is never written anywhere.
    return _CHALLENGE_PREFIX + hashlib.sha256(challenge).hexdigest()


class ChallengeStore:
    """Single-use challenges with a TTL. Valkey is the right place: they are ephemeral, and
    losing one only means the passkey prompt has to start again."""

    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    async def put(self, challenge: bytes, pending: PendingChallenge) -> None:
        value = json.dumps(
            {"purpose": pending.purpose, "binding": pending.binding, "user_id": pending.user_id}
        )
        await self.redis.set(_challenge_key(challenge), value, ex=self.ttl_seconds, nx=True)

    async def take(self, challenge: bytes) -> PendingChallenge | None:
        """Atomically read and delete: a challenge can be used at most once."""
        raw = await self.redis.getdel(_challenge_key(challenge))
        if not isinstance(raw, str):
            return None
        try:
            data = json.loads(raw)
            purpose = data["purpose"]
            if purpose not in ("register", "login"):
                return None
            return PendingChallenge(
                purpose=purpose, binding=str(data["binding"]), user_id=data.get("user_id")
            )
        except (ValueError, KeyError, TypeError):
            return None


def login_flow_binding(flow_token: str) -> str:
    """What a sign-in challenge is bound to: the hash of the browser's flow cookie."""
    return hash_token(f"webauthn-flow:{flow_token}")


# --- results ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class PasskeyOptions:
    options: dict[str, Any]  # PublicKeyCredential{Creation,Request}OptionsJSON
    expires_in_seconds: int


@dataclass(frozen=True)
class PasskeyOverview:
    enabled: bool
    rp_id: str | None
    max_passkeys: int
    passkeys: list[WebAuthnCredential]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _transports(values: list[AuthenticatorTransport] | None) -> list[str]:
    return [t.value for t in values or [] if t.value in _KNOWN_TRANSPORTS]


def _challenge_of(credential: RegistrationCredential | AuthenticationCredential) -> bytes:
    return parse_client_data_json(credential.response.client_data_json).challenge


class PasskeyService:
    def __init__(self, db: AsyncSession, settings: Settings, redis: Redis) -> None:
        self.db = db
        self.settings = settings
        self.auth = AuthService(db, settings)
        self.audit = AuditService(db)
        self.repo = PasskeyRepository(db)
        self.challenges = ChallengeStore(redis, settings.webauthn_challenge_ttl_seconds)

    # --- configuration ---------------------------------------------------------------

    def _relying_party(self) -> tuple[str, list[str]]:
        rp_id = self.settings.webauthn_rp_id
        if rp_id is None or not self.settings.webauthn_origins:
            raise PasskeysDisabled()
        return rp_id, self.settings.webauthn_origins

    @property
    def _timeout_ms(self) -> int:
        return self.settings.webauthn_challenge_ttl_seconds * 1000

    # --- managing the owner's passkeys (signed in) ---------------------------------------

    async def overview(self, user: User) -> PasskeyOverview:
        return PasskeyOverview(
            enabled=self.settings.passkeys_enabled,
            rp_id=self.settings.webauthn_rp_id,
            max_passkeys=self.settings.webauthn_max_credentials,
            passkeys=await self.repo.list_for_user(user.id),
        )

    async def registration_options(
        self, ctx: AuthContext, password: str, client: ClientInfo
    ) -> PasskeyOptions:
        """Step 1 of adding a passkey: confirm the password, then issue the options for
        ``navigator.credentials.create()`` with a challenge bound to this session."""
        rp_id, _ = self._relying_party()
        user = ctx.user
        await self.auth.confirm_password(user, password, client, purpose="passkey_register")
        existing = await self.repo.list_for_user(user.id)
        self._check_limit(len(existing))

        options = generate_registration_options(
            rp_id=rp_id,
            rp_name=self.settings.webauthn_rp_name,
            user_name=user.username,
            # The WebAuthn user handle: our opaque user id (no personal data).
            user_id=user.id.bytes,
            user_display_name=user.display_name or user.username,
            timeout=self._timeout_ms,
            attestation=AttestationConveyancePreference.NONE,
            authenticator_selection=AuthenticatorSelectionCriteria(
                # Discoverable: sign in without typing the username first.
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=[
                PublicKeyCredentialDescriptor(
                    id=row.credential_id,
                    transports=[AuthenticatorTransport(t) for t in row.transports],
                )
                for row in existing
            ],
            hints=[PublicKeyCredentialHint.CLIENT_DEVICE],
        )
        await self.challenges.put(
            options.challenge,
            PendingChallenge(purpose="register", binding=str(ctx.session.id), user_id=str(user.id)),
        )
        return PasskeyOptions(
            options=options_to_json_dict(options),
            expires_in_seconds=self.settings.webauthn_challenge_ttl_seconds,
        )

    async def register(
        self, ctx: AuthContext, credential: dict[str, Any], name: str, client: ClientInfo
    ) -> WebAuthnCredential:
        """Step 2: verify the new passkey against the challenge of step 1 and save it."""
        rp_id, origins = self._relying_party()
        user = ctx.user
        clean_name = (
            normalize_profile_text(name, field="name", max_chars=PASSKEY_NAME_MAX_CHARS)
            or DEFAULT_PASSKEY_NAME
        )

        try:
            parsed = parse_registration_credential_json(credential)
            challenge = _challenge_of(parsed)
        except (WebAuthnException, ValueError, TypeError, KeyError):
            await self._add_failed(user, client, "malformed")
            raise PasskeyInvalid() from None

        pending = await self.challenges.take(challenge)
        if (
            pending is None
            or pending.purpose != "register"
            or pending.binding != str(ctx.session.id)
            or pending.user_id != str(user.id)
        ):
            await self._add_failed(user, client, "challenge_invalid")
            raise PasskeyExpired(status_code=400)

        try:
            verified = verify_registration_response(
                credential=parsed,
                expected_challenge=challenge,
                expected_rp_id=rp_id,
                expected_origin=origins,
                require_user_verification=True,
            )
        except (WebAuthnException, ValueError, TypeError, KeyError):
            await self._add_failed(user, client, "verification_failed")
            raise PasskeyInvalid() from None

        self._check_limit(await self.repo.count_for_user(user.id))
        if await self.repo.get_by_credential_id(verified.credential_id) is not None:
            raise PasskeyAlreadyRegistered()

        row = await self.repo.add(
            WebAuthnCredential(
                user_id=user.id,
                credential_id=verified.credential_id,
                public_key=verified.credential_public_key,
                sign_count=verified.sign_count,
                transports=_transports(parsed.response.transports),
                name=clean_name,
                aaguid=verified.aaguid,
                backed_up=verified.credential_backed_up,
            )
        )
        await self.audit.record(
            PASSKEY_ADDED,
            "success",
            actor_type="user",
            actor_id=user.id,
            user_id=user.id,
            resource_type="passkey",
            resource_id=str(row.id),
            ip_address=client.ip_address,
            details={
                # A confirmed password: restarts the lockout count like any correct one.
                "subject_key": login_subject_key(user.username),
                "name": clean_name,
                "backed_up": row.backed_up,
                "aaguid": row.aaguid,
            },
        )
        await self.db.commit()
        logger.info("passkey_added", extra={"user_id": str(user.id), "passkey_id": str(row.id)})
        return row

    async def rename(
        self, ctx: AuthContext, passkey_id: uuid.UUID, name: str, client: ClientInfo
    ) -> WebAuthnCredential:
        row = await self._owned(ctx.user, passkey_id)
        clean_name = normalize_profile_text(name, field="name", max_chars=PASSKEY_NAME_MAX_CHARS)
        if clean_name is None:
            clean_name = DEFAULT_PASSKEY_NAME
        old_name = row.name
        if clean_name != old_name:
            row.name = clean_name
            await self.audit.record(
                PASSKEY_RENAMED,
                "success",
                actor_type="user",
                actor_id=ctx.user.id,
                user_id=ctx.user.id,
                resource_type="passkey",
                resource_id=str(row.id),
                ip_address=client.ip_address,
                details={"name": clean_name, "renamed_from": old_name},
            )
            await self.db.commit()
        return row

    async def delete(
        self, ctx: AuthContext, passkey_id: uuid.UUID, password: str, client: ClientInfo
    ) -> None:
        """Confirmed with the password (wrong ones count toward the lockout)."""
        user = ctx.user
        row = await self._owned(user, passkey_id)
        subject_key = await self.auth.confirm_password(
            user, password, client, purpose="passkey_delete"
        )
        name = row.name
        await self.repo.delete(row.id)
        await self.audit.record(
            PASSKEY_DELETED,
            "success",
            actor_type="user",
            actor_id=user.id,
            user_id=user.id,
            resource_type="passkey",
            resource_id=str(passkey_id),
            ip_address=client.ip_address,
            details={"subject_key": subject_key, "name": name},
        )
        await self.db.commit()
        logger.info(
            "passkey_deleted", extra={"user_id": str(user.id), "passkey_id": str(passkey_id)}
        )

    # --- signing in (public) ---------------------------------------------------------------

    async def login_options(self, flow_token: str) -> PasskeyOptions:
        """Options for ``navigator.credentials.get()``: no username, no credential list (the
        device offers the passkeys it has for this site), user verification required."""
        rp_id, _ = self._relying_party()
        binding = login_flow_binding(flow_token)
        options = generate_authentication_options(
            rp_id=rp_id,
            timeout=self._timeout_ms,
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        await self.challenges.put(
            options.challenge, PendingChallenge(purpose="login", binding=binding, user_id=None)
        )
        return PasskeyOptions(
            options=options_to_json_dict(options),
            expires_in_seconds=self.settings.webauthn_challenge_ttl_seconds,
        )

    async def login(
        self, credential: dict[str, Any], flow_token: str | None, client: ClientInfo
    ) -> LoginResult:
        rp_id, origins = self._relying_party()

        try:
            parsed = parse_authentication_credential_json(credential)
            challenge = _challenge_of(parsed)
        except (WebAuthnException, ValueError, TypeError, KeyError):
            await self._login_failed(UNKNOWN_PASSKEY_SUBJECT, client, "malformed")
            raise PasskeyRejected() from None

        # Taken first: whatever happens next, this challenge can never be used again.
        pending = await self.challenges.take(challenge)

        row = await self.repo.get_by_credential_id(parsed.raw_id)
        if row is None or not row.user.is_active:
            await self._login_failed(UNKNOWN_PASSKEY_SUBJECT, client, "unknown_or_inactive")
            raise PasskeyRejected()
        user = row.user
        subject_key = login_subject_key(user.username)
        await self.auth.enforce_lockout(subject_key, client)

        binding = login_flow_binding(flow_token) if flow_token else None
        if (
            pending is None
            or pending.purpose != "login"
            or binding is None
            or pending.binding != binding
        ):
            await self._login_failed(subject_key, client, "challenge_invalid", user=user)
            raise PasskeyExpired()

        try:
            verified = verify_authentication_response(
                credential=parsed,
                expected_challenge=challenge,
                expected_rp_id=rp_id,
                expected_origin=origins,
                credential_public_key=row.public_key,
                credential_current_sign_count=row.sign_count,
                require_user_verification=True,
            )
        except (WebAuthnException, ValueError, TypeError, KeyError):
            await self._login_failed(subject_key, client, "verification_failed", user=user)
            raise PasskeyRejected() from None

        # A discoverable passkey says whose it is; it must be the owner of this credential.
        handle = parsed.response.user_handle
        if handle is not None and handle != user.id.bytes:
            await self._login_failed(subject_key, client, "user_handle_mismatch", user=user)
            raise PasskeyRejected()

        row.sign_count = verified.new_sign_count
        row.backed_up = verified.credential_backed_up
        row.last_used_at = _utcnow()
        return await self.auth.start_session(
            user,
            client,
            subject_key=subject_key,
            method="passkey",
            details={"passkey_id": str(row.id)},
        )

    # --- internals -------------------------------------------------------------------------

    def _check_limit(self, count: int) -> None:
        limit = self.settings.webauthn_max_credentials
        if count >= limit:
            raise PasskeyLimitReached(details={"max": limit})

    async def _owned(self, user: User, passkey_id: uuid.UUID) -> WebAuthnCredential:
        row = await self.repo.get_for_user(user.id, passkey_id)
        if row is None:
            raise NotFound()
        return row

    async def _login_failed(
        self, subject_key: str, client: ClientInfo, reason: str, *, user: User | None = None
    ) -> None:
        await self.auth.record_failure(
            subject_key, client, reason=reason, user=user, method="passkey"
        )

    async def _add_failed(self, user: User, client: ClientInfo, reason: str) -> None:
        await self.audit.record(
            PASSKEY_ADD_FAILED,
            "failure",
            actor_type="user",
            actor_id=user.id,
            user_id=user.id,
            resource_type="passkey",
            ip_address=client.ip_address,
            details={"reason": reason},
        )
        await self.db.commit()
        logger.warning("passkey_add_failed", extra={"reason": reason})
