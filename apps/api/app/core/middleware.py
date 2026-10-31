"""Pure-ASGI middlewares (no BaseHTTPMiddleware, so SSE/WebSocket streaming stays intact)."""

from __future__ import annotations

import hmac
import re
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import cookie_parser
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings
from app.core.errors import CsrfFailed, error_body
from app.core.security import csrf_binding, verify_csrf_token

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class RequestContextMiddleware:
    """Assigns a request id (reused from ``X-Request-ID`` if well-formed) and marks
    API responses as non-cacheable."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get("x-request-id", "")
        request_id = incoming if _REQUEST_ID_RE.fullmatch(incoming) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        is_api = scope["path"].startswith("/api/")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                if is_api and "cache-control" not in headers:
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_wrapper)


class CSRFMiddleware:
    """Rejects state-changing ``/api/`` requests without a valid CSRF token.

    The token must be sent both as the CSRF cookie and in the CSRF header
    (double submit), and its signature must match the current session cookie.
    Applied globally so no new endpoint can forget it.
    """

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] in SAFE_METHODS
            or not scope["path"].startswith("/api/")
        ):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        cookies = cookie_parser(headers.get("cookie", ""))
        header_token = headers.get(self.settings.csrf_header_name)
        cookie_token = cookies.get(self.settings.csrf_cookie_name)
        binding = csrf_binding(cookies.get(self.settings.session_cookie_name))

        valid = (
            header_token is not None
            and cookie_token is not None
            and hmac.compare_digest(header_token, cookie_token)
            and verify_csrf_token(
                self.settings.secret_key.get_secret_value(), header_token, binding
            )
        )
        if not valid:
            response = JSONResponse(
                error_body(CsrfFailed.code, CsrfFailed.message), status_code=CsrfFailed.status_code
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
