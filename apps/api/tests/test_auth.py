from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import select, update

from app.core.security import hash_token
from app.models import AuditLog, Session, User
from tests.conftest import (
    OWNER_PASSWORD,
    OWNER_USERNAME,
    AppFactory,
    csrf_headers,
    login,
    make_client,
)


def _set_cookie_headers(resp: httpx.Response) -> list[str]:
    return resp.headers.get_list("set-cookie")


async def _audit_actions(app: FastAPI) -> list[AuditLog]:
    async with app.state.db.sessionmaker() as s:
        rows = await s.execute(select(AuditLog).order_by(AuditLog.created_at))
        return list(rows.scalars())


# --- login ---------------------------------------------------------------------


async def test_login_sets_secure_cookies_and_me_works(
    client: httpx.AsyncClient, owner: User
) -> None:
    await client.get("/api/v1/auth/csrf")
    pre_login_csrf = client.cookies.get("moloko_csrf")

    resp = await login(client)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["username"] == OWNER_USERNAME
    assert body["user"]["display_name"] == "Owner"
    assert "password_hash" not in body["user"]

    cookies = _set_cookie_headers(resp)
    session_cookie = next(c for c in cookies if c.startswith("moloko_session="))
    assert "HttpOnly" in session_cookie
    assert "Secure" in session_cookie
    assert "samesite=lax" in session_cookie.lower()
    csrf_cookie = next(c for c in cookies if c.startswith("moloko_csrf="))
    assert "HttpOnly" not in csrf_cookie
    assert "samesite=strict" in csrf_cookie.lower()
    # CSRF token is rotated on login so it is bound to the new session.
    assert client.cookies.get("moloko_csrf") != pre_login_csrf

    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["id"] == str(owner.id)
    assert me.json()["session"]["expires_at"]


async def test_session_token_is_stored_hashed(
    client: httpx.AsyncClient, owner: User, app: FastAPI
) -> None:
    await login(client)
    raw = client.cookies.get("moloko_session")
    assert raw
    async with app.state.db.sessionmaker() as s:
        sessions = list((await s.execute(select(Session))).scalars())
    assert len(sessions) == 1
    assert sessions[0].token_hash == hash_token(raw)
    assert sessions[0].token_hash != raw
    expected_ttl = timedelta(hours=168)
    assert abs((sessions[0].expires_at - datetime.now(UTC)) - expected_ttl) < timedelta(minutes=1)


async def test_username_is_case_insensitive(client: httpx.AsyncClient, owner: User) -> None:
    resp = await login(client, username="  OWNER ")
    assert resp.status_code == 200


async def test_wrong_password_and_unknown_user_look_identical(
    client: httpx.AsyncClient, owner: User
) -> None:
    bad_pw = await login(client, password="definitely wrong")
    unknown = await login(client, username="nobody", password="definitely wrong")
    assert bad_pw.status_code == unknown.status_code == 401
    e1, e2 = bad_pw.json()["error"], unknown.json()["error"]
    assert e1["code"] == e2["code"] == "invalid_credentials"
    assert e1["message"] == e2["message"]
    assert e1["id"] != e2["id"]
    assert "moloko_session" not in client.cookies


async def test_inactive_user_cannot_log_in_and_loses_session(
    client: httpx.AsyncClient, owner: User, app: FastAPI
) -> None:
    assert (await login(client)).status_code == 200
    async with app.state.db.sessionmaker() as s:
        await s.execute(update(User).values(is_active=False))
        await s.commit()
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert (await login(client)).status_code == 401


async def test_validation_error_never_echoes_password(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "", "password": "my-super-secret-password", "extra": 1},
        headers=await csrf_headers(client),
    )
    assert resp.status_code == 422
    assert "my-super-secret-password" not in resp.text
    error = resp.json()["error"]
    assert error["code"] == "validation_error"
    assert {tuple(d["loc"]) for d in error["details"]} >= {("body", "username"), ("body", "extra")}


# --- CSRF ----------------------------------------------------------------------


async def test_login_without_csrf_is_rejected(client: httpx.AsyncClient, owner: User) -> None:
    resp = await client.post(
        "/api/v1/auth/login", json={"username": OWNER_USERNAME, "password": OWNER_PASSWORD}
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "csrf_failed"


async def test_csrf_header_must_match_cookie(client: httpx.AsyncClient, owner: User) -> None:
    await client.get("/api/v1/auth/csrf")
    other = await client.get("/api/v1/auth/csrf")  # rotates the cookie
    stale = other.json()["csrf_token"]
    await client.get("/api/v1/auth/csrf")
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": OWNER_USERNAME, "password": OWNER_PASSWORD},
        headers={"X-CSRF-Token": stale},
    )
    assert resp.status_code == 403


async def test_forged_csrf_token_is_rejected(client: httpx.AsyncClient, owner: User) -> None:
    forged = "abc.def"
    client.cookies.set("moloko_csrf", forged, domain="testserver")
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": OWNER_USERNAME, "password": OWNER_PASSWORD},
        headers={"X-CSRF-Token": forged},
    )
    assert resp.status_code == 403


async def test_pre_login_csrf_token_is_useless_after_login(
    client: httpx.AsyncClient, owner: User
) -> None:
    anon_token = (await client.get("/api/v1/auth/csrf")).json()["csrf_token"]
    assert (await login(client)).status_code == 200
    client.cookies.set("moloko_csrf", anon_token, domain="testserver")
    resp = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": anon_token})
    assert resp.status_code == 403
    assert (await client.get("/api/v1/auth/me")).status_code == 200  # still logged in


# --- session lifecycle -----------------------------------------------------------


async def test_me_requires_session(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    error = resp.json()["error"]
    assert error["code"] == "not_authenticated"
    assert error["id"]


async def test_garbage_session_cookie_is_rejected(client: httpx.AsyncClient) -> None:
    client.cookies.set("moloko_session", "garbage", domain="testserver")
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_logout_revokes_session(client: httpx.AsyncClient, owner: User, app: FastAPI) -> None:
    await login(client)
    raw = client.cookies.get("moloko_session")
    assert raw

    resp = await client.post("/api/v1/auth/logout", headers=await csrf_headers(client))
    assert resp.status_code == 204
    assert "moloko_session" not in client.cookies
    assert (await client.get("/api/v1/auth/me")).status_code == 401

    # Replaying the old cookie must not work either: the session is revoked server-side.
    client.cookies.set("moloko_session", raw, domain="testserver")
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    async with app.state.db.sessionmaker() as s:
        session = (await s.execute(select(Session))).scalar_one()
    assert session.revoked_at is not None


async def test_logout_without_session_is_harmless(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/logout", headers=await csrf_headers(client))
    assert resp.status_code == 204


async def test_expired_session_is_rejected(
    client: httpx.AsyncClient, owner: User, app: FastAPI
) -> None:
    await login(client)
    async with app.state.db.sessionmaker() as s:
        await s.execute(update(Session).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        await s.commit()
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_sessions_on_two_devices_are_independent(app: FastAPI, owner: User) -> None:
    async with make_client(app) as laptop, make_client(app) as phone:
        assert (await login(laptop)).status_code == 200
        assert (await login(phone)).status_code == 200
        assert laptop.cookies.get("moloko_session") != phone.cookies.get("moloko_session")
        await laptop.post("/api/v1/auth/logout", headers=await csrf_headers(laptop))
        assert (await laptop.get("/api/v1/auth/me")).status_code == 401
        assert (await phone.get("/api/v1/auth/me")).status_code == 200


# --- brute-force protection -------------------------------------------------------


async def _fail(client: httpx.AsyncClient, n: int, username: str = OWNER_USERNAME) -> None:
    for _ in range(n):
        assert (await login(client, username=username, password="wrong")).status_code == 401


async def test_lockout_after_repeated_failures(app_factory: AppFactory, owner: User) -> None:
    app = await app_factory(login_max_failures=3, login_lockout_seconds=1)
    async with make_client(app) as client:
        await _fail(client, 3)
        blocked = await login(client)  # even the correct password is refused now
        assert blocked.status_code == 429
        assert blocked.json()["error"]["code"] == "too_many_attempts"
        assert blocked.headers["retry-after"] == "1"

        await asyncio.sleep(1.2)
        assert (await login(client)).status_code == 200


async def test_lockout_applies_to_unknown_usernames(app_factory: AppFactory) -> None:
    app = await app_factory(login_max_failures=2)
    async with make_client(app) as client:
        await _fail(client, 2, username="ghost")
        assert (await login(client, username="ghost", password="x")).status_code == 429


async def test_successful_login_resets_failure_count(app_factory: AppFactory, owner: User) -> None:
    app = await app_factory(login_max_failures=3)
    async with make_client(app) as client:
        await _fail(client, 2)
        assert (await login(client)).status_code == 200
        await _fail(client, 2)
        assert (await login(client)).status_code == 200


# --- audit trail -------------------------------------------------------------------


async def test_auth_events_are_audited_without_secrets(
    client: httpx.AsyncClient, owner: User, app: FastAPI
) -> None:
    await login(client, password="wrong-password-123")
    await login(client)
    await client.post("/api/v1/auth/logout", headers=await csrf_headers(client))

    entries = await _audit_actions(app)
    actions = [e.action for e in entries]
    assert actions[-3:] == ["auth.login_failed", "auth.login", "auth.logout"]

    failed, ok, out = entries[-3:]
    assert failed.outcome == "failure" and failed.actor_type == "anonymous"
    assert ok.outcome == "success" and ok.user_id == owner.id
    assert out.user_id == owner.id

    dumped: list[Any] = [e.details for e in entries]
    assert "wrong-password-123" not in repr(dumped)
    assert OWNER_PASSWORD not in repr(dumped)
