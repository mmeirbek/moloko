from __future__ import annotations

from fastapi import Response

from app.core.config import Settings
from app.core.security import csrf_binding, generate_csrf_token


def set_csrf_cookie(response: Response, settings: Settings, session_token: str | None) -> str:
    """Mint a CSRF token bound to ``session_token`` and store it in a JS-readable cookie."""
    token = generate_csrf_token(settings.secret_key.get_secret_value(), csrf_binding(session_token))
    response.set_cookie(
        settings.csrf_cookie_name,
        token,
        max_age=settings.session_ttl_hours * 3600,
        path="/",
        secure=settings.cookie_secure,
        httponly=False,  # the frontend must read it to echo it in the header
        samesite="strict",
    )
    return token


def set_session_cookie(response: Response, settings: Settings, session_token: str) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        max_age=settings.session_ttl_hours * 3600,
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
