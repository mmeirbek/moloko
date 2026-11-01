from __future__ import annotations

import httpx

from app import __version__
from tests.conftest import AppFactory, make_client


async def test_liveness(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_health_ok_without_auth(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"database": "ok", "redis": "ok"}
    assert body["version"] == __version__


async def test_health_degraded_when_redis_down(app_factory: AppFactory) -> None:
    app = await app_factory(redis_url="redis://127.0.0.1:1/0")
    async with make_client(app) as client:
        resp = await client.get("/api/v1/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["checks"] == {"database": "ok", "redis": "error"}


async def test_health_degraded_when_database_down(app_factory: AppFactory) -> None:
    app = await app_factory(database_url="postgresql+asyncpg://moloko:moloko@127.0.0.1:1/none")
    async with make_client(app) as client:
        resp = await client.get("/api/v1/health")
    assert resp.status_code == 503
    assert resp.json()["checks"] == {"database": "error", "redis": "ok"}


async def test_api_responses_have_request_id_and_no_store(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/health/live")
    assert len(resp.headers["x-request-id"]) >= 8
    assert resp.headers["cache-control"] == "no-store"

    resp = await client.get("/api/v1/health/live", headers={"X-Request-ID": "client-req-123"})
    assert resp.headers["x-request-id"] == "client-req-123"

    resp = await client.get("/api/v1/health/live", headers={"X-Request-ID": "bad id!"})
    assert resp.headers["x-request-id"] != "bad id!"


async def test_unknown_route_uses_error_envelope(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/does-not-exist")
    assert resp.status_code in (401, 404)
    error = resp.json()["error"]
    assert set(error) >= {"id", "code", "message"}


async def test_login_while_database_down_is_a_clear_503(app_factory: AppFactory) -> None:
    app = await app_factory(database_url="postgresql+asyncpg://moloko:moloko@127.0.0.1:1/none")
    async with make_client(app, raise_app_exceptions=False) as client:
        await client.get("/api/v1/auth/csrf")
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "owner", "password": "whatever"},
            headers={"X-CSRF-Token": client.cookies["moloko_csrf"]},
        )
    assert resp.status_code == 503
    error = resp.json()["error"]
    assert error["code"] == "database_unavailable"
    assert error["id"]
    assert resp.headers["retry-after"] == "10"


def test_unrelated_os_errors_are_not_reported_as_database_outages() -> None:
    from app.core.errors import classify_infrastructure_error

    assert classify_infrastructure_error(FileNotFoundError("x")) is None
    assert classify_infrastructure_error(ValueError("x")) is None
