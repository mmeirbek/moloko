"""Every API route requires a session unless it is on the explicit public allow-list."""

from __future__ import annotations

import re
import uuid

import httpx
from fastapi import FastAPI

from app.api.v1.router import PUBLIC_ROUTES
from tests.conftest import csrf_headers


def _api_routes(app: FastAPI) -> list[tuple[str, str]]:
    # The OpenAPI schema is the public, version-stable list of every HTTP route.
    # Hence the rule in app/api/v1/router.py: never use include_in_schema=False.
    paths = app.openapi()["paths"]
    return [
        (method.upper(), path)
        for path, operations in paths.items()
        if path.startswith("/api/")
        for method in operations
    ]


async def test_public_allow_list_matches_real_routes(app: FastAPI) -> None:
    real = set(_api_routes(app))
    assert real >= PUBLIC_ROUTES, f"stale entries: {PUBLIC_ROUTES - real}"


async def test_all_other_routes_require_authentication(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    protected = [r for r in _api_routes(app) if r not in PUBLIC_ROUTES]
    assert protected, "expected at least one protected route"
    headers = await csrf_headers(client)  # pass CSRF so we test auth, not CSRF
    for method, path in protected:
        url = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)
        resp = await client.request(method, url, headers=headers, json={})
        assert resp.status_code == 401, f"{method} {path} returned {resp.status_code}"


async def test_openapi_documents_our_error_envelope(app: FastAPI) -> None:
    schema = app.openapi()
    components = schema["components"]["schemas"]
    assert "HTTPValidationError" not in components
    assert "ErrorResponse" in components
    login_422 = schema["paths"]["/api/v1/auth/login"]["post"]["responses"]["422"]
    assert login_422["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorResponse")
