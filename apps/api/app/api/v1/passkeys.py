"""Passkeys: sign in with Face ID / Touch ID (WebAuthn). Policy: app.services.passkeys."""

from __future__ import annotations

import re
import secrets
import uuid

from fastapi import APIRouter, Request, Response, status

from app.api.deps import Client, CurrentAuth, DbSession, RedisDep, SettingsDep
from app.api.v1.auth import signed_in
from app.core.cookies import clear_passkey_flow_cookie, set_passkey_flow_cookie
from app.schemas.auth import MeResponse
from app.schemas.passkeys import (
    PasskeyListOut,
    PasskeyLoginVerify,
    PasskeyOptionsOut,
    PasskeyOut,
    PasskeyRegisterVerify,
    PasskeyRename,
    PasswordConfirm,
)
from app.services.passkeys import PasskeyService

PREFIX = "/auth/passkeys"
# The sign-in flow cookie goes back only to the two sign-in endpoints below.
LOGIN_FLOW_COOKIE_PATH = "/api/v1" + PREFIX + "/login"
_FLOW_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")  # secrets.token_urlsafe(32)

# Signing in with a passkey (deliberately public — listed in PUBLIC_ROUTES).
public_router = APIRouter(prefix=PREFIX, tags=["auth"])
# Managing the owner's passkeys (needs a session).
protected_router = APIRouter(prefix=PREFIX, tags=["auth"])


@protected_router.get("", response_model=PasskeyListOut, summary="The owner's passkeys")
async def list_passkeys(
    ctx: CurrentAuth, db: DbSession, settings: SettingsDep, redis: RedisDep
) -> PasskeyListOut:
    overview = await PasskeyService(db, settings, redis).overview(ctx.user)
    return PasskeyListOut(
        enabled=overview.enabled,
        rp_id=overview.rp_id,
        max_passkeys=overview.max_passkeys,
        passkeys=[PasskeyOut.model_validate(p) for p in overview.passkeys],
    )


@protected_router.post(
    "/register/options",
    response_model=PasskeyOptionsOut,
    summary="Start adding a passkey (confirmed with the password)",
)
async def registration_options(
    body: PasswordConfirm,
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    redis: RedisDep,
    client: Client,
) -> PasskeyOptionsOut:
    result = await PasskeyService(db, settings, redis).registration_options(
        ctx, body.password, client
    )
    return PasskeyOptionsOut(options=result.options, expires_in_seconds=result.expires_in_seconds)


@protected_router.post(
    "/register/verify",
    response_model=PasskeyOut,
    status_code=status.HTTP_201_CREATED,
    summary="Finish adding a passkey (the browser's answer to register/options)",
)
async def register(
    body: PasskeyRegisterVerify,
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    redis: RedisDep,
    client: Client,
) -> PasskeyOut:
    row = await PasskeyService(db, settings, redis).register(
        ctx, body.credential, body.name, client
    )
    return PasskeyOut.model_validate(row)


@protected_router.patch("/{passkey_id}", response_model=PasskeyOut, summary="Rename a passkey")
async def rename_passkey(
    passkey_id: uuid.UUID,
    body: PasskeyRename,
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    redis: RedisDep,
    client: Client,
) -> PasskeyOut:
    row = await PasskeyService(db, settings, redis).rename(ctx, passkey_id, body.name, client)
    return PasskeyOut.model_validate(row)


@protected_router.delete(
    "/{passkey_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a passkey (confirmed with the password)",
)
async def delete_passkey(
    passkey_id: uuid.UUID,
    body: PasswordConfirm,
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    redis: RedisDep,
    client: Client,
) -> Response:
    await PasskeyService(db, settings, redis).delete(ctx, passkey_id, body.password, client)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@public_router.post(
    "/login/options",
    response_model=PasskeyOptionsOut,
    summary="Start signing in with a passkey (no username needed)",
)
async def login_options(
    request: Request,
    response: Response,
    db: DbSession,
    settings: SettingsDep,
    redis: RedisDep,
) -> PasskeyOptionsOut:
    # One flow cookie per browser; kept while valid so several open tabs all keep working.
    token = request.cookies.get(settings.webauthn_cookie_name) or ""
    if not _FLOW_TOKEN_RE.fullmatch(token):
        token = secrets.token_urlsafe(32)
    result = await PasskeyService(db, settings, redis).login_options(token)
    set_passkey_flow_cookie(
        response,
        settings,
        token,
        max_age=result.expires_in_seconds,
        path=LOGIN_FLOW_COOKIE_PATH,
    )
    return PasskeyOptionsOut(options=result.options, expires_in_seconds=result.expires_in_seconds)


@public_router.post(
    "/login/verify",
    response_model=MeResponse,
    summary="Sign in with a passkey (creates a session exactly like the password login)",
)
async def login_verify(
    body: PasskeyLoginVerify,
    request: Request,
    response: Response,
    db: DbSession,
    settings: SettingsDep,
    redis: RedisDep,
    client: Client,
) -> MeResponse:
    result = await PasskeyService(db, settings, redis).login(
        body.credential, request.cookies.get(settings.webauthn_cookie_name), client
    )
    clear_passkey_flow_cookie(response, settings, path=LOGIN_FLOW_COOKIE_PATH)
    return signed_in(response, settings, result)
