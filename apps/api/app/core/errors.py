"""Unified error model (spec sections 12 and 22).

Every error response has the shape ``{"error": {"id", "code", "message", "details?"}}``.
The ``id`` is unique per occurrence and is also written to the server log, so the
owner can match what the UI shows with the technical details that stay on the server.
"""

from __future__ import annotations

import logging
import traceback
import uuid
from typing import Any

import asyncpg
import redis.exceptions
import sqlalchemy.exc
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("moloko.errors")


class AppError(Exception):
    """An expected, user-facing error. Never put secrets or internals in ``message``."""

    status_code: int = 400
    code: str = "bad_request"
    message: str = "The request could not be processed."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details
        self.headers = headers
        super().__init__(self.message)


class NotAuthenticated(AppError):
    status_code = 401
    code = "not_authenticated"
    message = "Authentication required."


class InvalidCredentials(AppError):
    status_code = 401
    code = "invalid_credentials"
    message = "Invalid username or password."


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"
    message = "You are not allowed to do this."


class CsrfFailed(AppError):
    status_code = 403
    code = "csrf_failed"
    message = "Security token is missing or invalid. Reload the page and try again."


class NotFound(AppError):
    status_code = 404
    code = "not_found"
    message = "Not found."


class Conflict(AppError):
    status_code = 409
    code = "conflict"
    message = "The request conflicts with the current state."


class TooManyAttempts(AppError):
    status_code = 429
    code = "too_many_attempts"
    message = "Too many failed attempts. Try again later."


_DB_CONNECTIVITY_ERRORS: tuple[type[BaseException], ...] = (
    sqlalchemy.exc.OperationalError,
    sqlalchemy.exc.InterfaceError,
    sqlalchemy.exc.DisconnectionError,
    asyncpg.PostgresConnectionError,
    asyncpg.CannotConnectNowError,
    asyncpg.InterfaceError,
)
_NETWORK_ERRORS: tuple[type[BaseException], ...] = (OSError, TimeoutError)


def _raised_inside(exc: BaseException, *packages: str) -> bool:
    for frame, _ in traceback.walk_tb(exc.__traceback__):
        module = frame.f_globals.get("__name__", "")
        if any(module == pkg or module.startswith(pkg + ".") for pkg in packages):
            return True
    return False


def classify_infrastructure_error(exc: BaseException) -> tuple[str, str] | None:
    """Map 'a dependency is down' failures to a clear 503 instead of a generic 500."""
    if isinstance(exc, _DB_CONNECTIVITY_ERRORS) or (
        isinstance(exc, _NETWORK_ERRORS) and _raised_inside(exc, "sqlalchemy", "asyncpg")
    ):
        return "database_unavailable", "The database is temporarily unavailable. Try again shortly."
    if isinstance(exc, redis.exceptions.ConnectionError | redis.exceptions.TimeoutError):
        return "redis_unavailable", "A background service is temporarily unavailable."
    return None


def new_error_id() -> str:
    return str(uuid.uuid4())


def error_body(
    code: str, message: str, *, error_id: str | None = None, details: Any = None
) -> dict[str, Any]:
    body: dict[str, Any] = {"id": error_id or new_error_id(), "code": code, "message": message}
    if details is not None:
        body["details"] = details
    return {"error": body}


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


_HTTP_CODES = {
    400: ("bad_request", "The request could not be processed."),
    401: ("not_authenticated", "Authentication required."),
    403: ("forbidden", "You are not allowed to do this."),
    404: ("not_found", "Not found."),
    405: ("method_not_allowed", "Method not allowed."),
    413: ("payload_too_large", "The request is too large."),
    415: ("unsupported_media_type", "Unsupported content type."),
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        error_id = new_error_id()
        log = logger.warning if exc.status_code < 500 else logger.error
        log(
            "app_error",
            extra={
                "error_id": error_id,
                "code": exc.code,
                "status": exc.status_code,
                "path": request.url.path,
                "request_id": _request_id(request),
            },
        )
        return JSONResponse(
            error_body(exc.code, exc.message, error_id=error_id, details=exc.details),
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Never echo submitted values back (they may contain passwords): keep only
        # where the problem is and what kind of problem it is.
        details = [
            {"loc": list(err.get("loc", ())), "msg": err.get("msg"), "type": err.get("type")}
            for err in exc.errors()
        ]
        return JSONResponse(
            error_body("validation_error", "Some fields are invalid.", details=details),
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, message = _HTTP_CODES.get(exc.status_code, ("http_error", "Request failed."))
        return JSONResponse(
            error_body(code, message),
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        error_id = new_error_id()
        infra = classify_infrastructure_error(exc)
        if infra is not None:
            code, message = infra
            logger.error(
                "dependency_unavailable",
                extra={
                    "error_id": error_id,
                    "code": code,
                    "error": type(exc).__name__,
                    "path": request.url.path,
                    "request_id": _request_id(request),
                },
            )
            return JSONResponse(
                error_body(code, message, error_id=error_id),
                status_code=503,
                headers={"Retry-After": "10"},
            )
        logger.exception(
            "unhandled_error",
            extra={
                "error_id": error_id,
                "path": request.url.path,
                "request_id": _request_id(request),
            },
        )
        return JSONResponse(
            error_body(
                "internal_error",
                "Something went wrong on the server. The error was logged.",
                error_id=error_id,
            ),
            status_code=500,
        )
