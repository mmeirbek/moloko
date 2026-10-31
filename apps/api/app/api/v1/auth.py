from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.api.deps import Client, CurrentAuth, DbSession, SettingsDep
from app.core.cookies import clear_session_cookie, set_csrf_cookie, set_session_cookie
from app.core.errors import NotAuthenticated
from app.schemas.auth import CsrfResponse, LoginRequest, MeResponse, SessionOut, UserOut
from app.services.auth import AuthService

# Endpoints here are reachable without a session (login itself, CSRF bootstrap, logout).
public_router = APIRouter(prefix="/auth", tags=["auth"])
# Endpoints here require a valid session.
protected_router = APIRouter(prefix="/auth", tags=["auth"])


def _me(ctx_user: object, ctx_session: object) -> MeResponse:
    return MeResponse(
        user=UserOut.model_validate(ctx_user), session=SessionOut.model_validate(ctx_session)
    )


@public_router.get("/csrf", response_model=CsrfResponse, summary="Issue a CSRF token")
async def issue_csrf(request: Request, response: Response, settings: SettingsDep) -> CsrfResponse:
    token = set_csrf_cookie(response, settings, request.cookies.get(settings.session_cookie_name))
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
    set_session_cookie(response, settings, result.token)
    set_csrf_cookie(response, settings, result.token)  # rotate: bind CSRF to the new session
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
    set_csrf_cookie(response, settings, None)
    return response


@protected_router.get("/me", response_model=MeResponse, summary="Current user and session")
async def me(ctx: CurrentAuth) -> MeResponse:
    return _me(ctx.user, ctx.session)
