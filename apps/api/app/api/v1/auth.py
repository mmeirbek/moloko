from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.api.deps import Client, CurrentAuth, DbSession, SettingsDep
from app.core.cookies import (
    clear_session_cookie,
    keep_csrf_cookie,
    set_csrf_cookie,
    set_session_cookie,
)
from app.core.errors import NotAuthenticated
from app.schemas.auth import (
    CsrfResponse,
    LoginRequest,
    MeResponse,
    SessionOut,
    SessionSettingsOut,
    SessionSettingsUpdate,
    UserOut,
)
from app.services.auth import AuthService, effective_session_ttl_hours

# Endpoints here are reachable without a session (login itself, CSRF bootstrap, logout).
public_router = APIRouter(prefix="/auth", tags=["auth"])
# Endpoints here require a valid session.
protected_router = APIRouter(prefix="/auth", tags=["auth"])


def _me(ctx_user: object, ctx_session: object) -> MeResponse:
    return MeResponse(
        user=UserOut.model_validate(ctx_user), session=SessionOut.model_validate(ctx_session)
    )


@public_router.get("/csrf", response_model=CsrfResponse, summary="Issue a CSRF token")
async def issue_csrf(
    request: Request, response: Response, db: DbSession, settings: SettingsDep
) -> CsrfResponse:
    session_token = request.cookies.get(settings.session_cookie_name)
    max_age = await AuthService(db, settings).csrf_cookie_max_age(session_token)
    token = set_csrf_cookie(response, settings, session_token, max_age=max_age)
    return CsrfResponse(csrf_token=token)


@public_router.post("/login", response_model=MeResponse, summary="Log in as the owner")
async def login(
    body: LoginRequest,
    response: Response,
    db: DbSession,
    settings: SettingsDep,
    client: Client,
) -> MeResponse:
    result = await AuthService(db, settings).login(body.username, body.password, client)
    set_session_cookie(response, settings, result.token, max_age=result.ttl_seconds)
    # Rotate: bind CSRF to the new session.
    set_csrf_cookie(response, settings, result.token, max_age=result.ttl_seconds)
    return _me(result.user, result.session)


@public_router.post(
    "/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Log out (revoke the session)"
)
async def logout(
    request: Request,
    response: Response,
    db: DbSession,
    settings: SettingsDep,
    client: Client,
) -> Response:
    service = AuthService(db, settings)
    try:
        ctx = await service.authenticate(request.cookies.get(settings.session_cookie_name))
    except NotAuthenticated:
        ctx = None
    if ctx is not None:
        await service.logout(ctx, client)
    response.status_code = status.HTTP_204_NO_CONTENT
    clear_session_cookie(response, settings)
    set_csrf_cookie(
        response, settings, None, max_age=effective_session_ttl_hours(settings, None) * 3600
    )
    return response


@protected_router.get("/me", response_model=MeResponse, summary="Current user and session")
async def me(ctx: CurrentAuth) -> MeResponse:
    return _me(ctx.user, ctx.session)


@protected_router.get(
    "/session-settings", response_model=SessionSettingsOut, summary="How long sign-ins last"
)
async def get_session_settings(
    ctx: CurrentAuth, db: DbSession, settings: SettingsDep
) -> SessionSettingsOut:
    return SessionSettingsOut.model_validate(AuthService(db, settings).session_settings(ctx))


@protected_router.put(
    "/session-settings",
    response_model=SessionSettingsOut,
    summary="Change how long sign-ins last (confirmed with the password)",
)
async def update_session_settings(
    body: SessionSettingsUpdate,
    request: Request,
    response: Response,
    ctx: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    client: Client,
) -> SessionSettingsOut:
    result = await AuthService(db, settings).change_session_ttl(
        ctx, body.ttl_hours, body.password, client
    )
    # The current session now lasts the new lifetime: its cookies must live as long.
    max_age = result.ttl_hours * 3600
    set_session_cookie(
        response, settings, request.cookies[settings.session_cookie_name], max_age=max_age
    )
    keep_csrf_cookie(
        response, settings, request.cookies[settings.csrf_cookie_name], max_age=max_age
    )
    return SessionSettingsOut.model_validate(result)
