"""Auth cookies. Their lifetime always comes from the caller: a session cookie lives
exactly as long as its session (which depends on the user's chosen lifetime), and the
CSRF cookie as long as the session it is bound to."""

from __future__ import annotations

from fastapi import Response

from app.core.config import Settings
from app.core.security import csrf_binding, generate_csrf_token


def set_csrf_cookie(
    response: Response, settings: Settings, session_token: str | None, *, max_age: int
) -> str:
    """Mint a CSRF token bound to ``session_token`` and store it in a JS-readable cookie."""
    token = generate_csrf_token(settings.secret_key.get_secret_value(), csrf_binding(session_token))
    keep_csrf_cookie(response, settings, token, max_age=max_age)
    return token


def keep_csrf_cookie(response: Response, settings: Settings, token: str, *, max_age: int) -> None:
    """Re-send an already valid CSRF token with a new lifetime (no rotation, so requests
    already in flight with the current token keep working)."""
    response.set_cookie(
        settings.csrf_cookie_name,
        token,
        max_age=max_age,
        path="/",
        secure=settings.cookie_secure,
        httponly=False,  # the frontend must read it to echo it in the header
        samesite="strict",
    )


def set_session_cookie(
    response: Response, settings: Settings, session_token: str, *, max_age: int
) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        max_age=max_age,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
