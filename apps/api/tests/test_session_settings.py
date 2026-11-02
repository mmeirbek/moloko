"""The owner's own session lifetime: GET/PUT /api/v1/auth/session-settings."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import select, update

from app.core.security import hash_token
from app.models import AuditLog, Session, User
from app.services.auth import login_subject_key
from tests.conftest import (
    OWNER_PASSWORD,
    OWNER_USERNAME,
    AppFactory,
    csrf_headers,
    logged_in_client,
    login,
    make_client,
    make_settings,
)

URL = "/api/v1/auth/session-settings"
HOUR = timedelta(hours=1)
TOLERANCE = timedelta(minutes=1)


async def _put(
    client: httpx.AsyncClient, ttl_hours: Any, password: str = OWNER_PASSWORD
) -> httpx.Response:
    return await client.put(
        URL,
        json={"ttl_hours": ttl_hours, "password": password},
        headers=await csrf_headers(client),
    )


def _max_age(resp: httpx.Response, cookie: str) -> int:
    header = next(c for c in resp.headers.get_list("set-cookie") if c.startswith(cookie + "="))
    match = re.search(r"max-age=(\d+)", header, re.IGNORECASE)
    assert match, header
    return int(match.group(1))


async def _session_of(app: FastAPI, client: httpx.AsyncClient) -> Session:
    raw = client.cookies.get("moloko_session")
    assert raw
    async with app.state.db.sessionmaker() as s:
        return (
            await s.execute(select(Session).where(Session.token_hash == hash_token(raw)))
        ).scalar_one()


async def _reload(app: FastAPI, session: Session) -> Session:
    async with app.state.db.sessionmaker() as s:
        return (await s.execute(select(Session).where(Session.id == session.id))).scalar_one()


async def _user(app: FastAPI) -> User:
    async with app.state.db.sessionmaker() as s:
        return (await s.execute(select(User))).scalar_one()


async def _audit(app: FastAPI, action: str) -> list[AuditLog]:
    async with app.state.db.sessionmaker() as s:
        rows = await s.execute(
            select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at)
        )
        return list(rows.scalars())


def _expires_in(session: Session, hours: int) -> bool:
    return abs(session.expires_at - (datetime.now(UTC) + hours * HOUR)) < TOLERANCE


# --- reading -------------------------------------------------------------------------


async def test_defaults_come_from_settings(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        resp = await client.get(URL)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        me = (await client.get("/api/v1/auth/me")).json()
    assert body == {
        "ttl_hours": 168,
        "default_ttl_hours": 168,
        "min_hours": 1,
        "max_hours": 2160,
        "uses_default": True,
        "current_session_expires_at": me["session"]["expires_at"],
    }


async def test_bounds_follow_configuration(app_factory: AppFactory, owner: User) -> None:
    app = await app_factory(session_ttl_hours=24, session_ttl_min_hours=2, session_ttl_max_hours=48)
    async with logged_in_client(app) as client:
        body = (await client.get(URL)).json()
        assert (body["ttl_hours"], body["min_hours"], body["max_hours"]) == (24, 2, 48)
        assert (await _put(client, 49)).status_code == 422
        assert (await _put(client, 1)).status_code == 422
        assert (await _put(client, 48)).status_code == 200


def test_default_must_lie_within_the_bounds() -> None:
    with pytest.raises(ValidationError):
        make_settings(session_ttl_hours=5, session_ttl_min_hours=6)
    with pytest.raises(ValidationError):
        make_settings(session_ttl_hours=200, session_ttl_max_hours=100)
    with pytest.raises(ValidationError):
        make_settings(session_ttl_max_hours=24 * 90 + 1)


# --- changing ------------------------------------------------------------------------


async def test_change_applies_to_current_session_cookies_and_audit(
    app: FastAPI, owner: User
) -> None:
    async with logged_in_client(app) as client:
        csrf_before = client.cookies.get("moloko_csrf")
        resp = await _put(client, 24)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ttl_hours"] == 24
        assert body["default_ttl_hours"] == 168
        assert body["uses_default"] is False

        session = await _session_of(app, client)
        assert _expires_in(session, 24)
        returned = datetime.fromisoformat(body["current_session_expires_at"])
        assert abs(returned - session.expires_at) < timedelta(seconds=1)

        # Both cookies now live exactly as long as the session; the CSRF token is kept.
        assert _max_age(resp, "moloko_session") == 24 * 3600
        assert _max_age(resp, "moloko_csrf") == 24 * 3600
        assert client.cookies.get("moloko_csrf") == csrf_before

        # Still signed in, and further changes work with the same token.
        me = await client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["session"]["expires_at"] == body["current_session_expires_at"]
        assert (await client.get(URL)).json() == body
        assert (await _put(client, 48)).status_code == 200

    assert (await _user(app)).session_ttl_hours == 48
    changes = await _audit(app, "auth.session_ttl_changed")
    assert len(changes) == 2
    first = changes[0]
    assert first.outcome == "success"
    assert first.actor_type == "user" and first.actor_id == owner.id and first.user_id == owner.id
    assert first.details["old_hours"] == 168
    assert first.details["new_hours"] == 24
    assert first.details["uses_default"] is False
    assert changes[1].details["old_hours"] == 24
    assert OWNER_PASSWORD not in repr([c.details for c in changes])


async def test_null_resets_to_the_default(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        assert (await _put(client, 24)).status_code == 200
        resp = await _put(client, None)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ttl_hours"] == 168
        assert body["uses_default"] is True
        assert _max_age(resp, "moloko_session") == 168 * 3600
        assert _expires_in(await _session_of(app, client), 168)
    assert (await _user(app)).session_ttl_hours is None
    last = (await _audit(app, "auth.session_ttl_changed"))[-1]
    assert (last.details["old_hours"], last.details["new_hours"]) == (24, 168)
    assert last.details["uses_default"] is True


async def test_new_sign_ins_use_the_users_lifetime(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        assert (await _put(client, 30)).status_code == 200
    async with make_client(app) as other:
        resp = await login(other)
        assert resp.status_code == 200
        assert _max_age(resp, "moloko_session") == 30 * 3600
        assert _max_age(resp, "moloko_csrf") == 30 * 3600
        assert _expires_in(await _session_of(app, other), 30)


async def test_narrowed_bounds_clamp_a_stored_choice(
    app: FastAPI, app_factory: AppFactory, owner: User
) -> None:
    async with logged_in_client(app) as client:
        assert (await _put(client, 720)).status_code == 200
    # Later the server is configured with a lower maximum: the stored choice is capped.
    narrowed = await app_factory(session_ttl_hours=24, session_ttl_max_hours=48)
    async with make_client(narrowed) as client:
        resp = await login(client)
        assert resp.status_code == 200
        assert _max_age(resp, "moloko_session") == 48 * 3600
        assert _expires_in(await _session_of(narrowed, client), 48)
        body = (await client.get(URL)).json()
        assert (body["ttl_hours"], body["uses_default"]) == (48, False)


async def test_other_sessions_are_shortened_never_extended(app: FastAPI, owner: User) -> None:
    async with make_client(app) as laptop, make_client(app) as phone, make_client(app) as old:
        for client in (laptop, phone, old):
            assert (await login(client)).status_code == 200
        old_session = await _session_of(app, old)  # revoked below: must stay untouched
        await old.post("/api/v1/auth/logout", headers=await csrf_headers(old))

        assert (await _put(laptop, 24)).status_code == 200
        phone_session = await _session_of(app, phone)
        assert _expires_in(phone_session, 24)
        assert (await phone.get("/api/v1/auth/me")).status_code == 200  # nobody signed out
        assert (await _reload(app, old_session)).expires_at == old_session.expires_at

        # A longer lifetime extends only the session that confirmed it.
        assert (await _put(laptop, 720)).status_code == 200
        assert _expires_in(await _session_of(app, laptop), 720)
        assert (await _session_of(app, phone)).expires_at == phone_session.expires_at

        # Sessions that already end sooner stay as they are.
        soon = datetime.now(UTC) + HOUR
        async with app.state.db.sessionmaker() as s:
            await s.execute(
                update(Session).where(Session.id == phone_session.id).values(expires_at=soon)
            )
            await s.commit()
        assert (await _put(laptop, 24)).status_code == 200
        assert abs((await _session_of(app, phone)).expires_at - soon) < timedelta(seconds=1)

    last = (await _audit(app, "auth.session_ttl_changed"))[-1]
    assert last.details["other_sessions_shortened"] == 0
    first = (await _audit(app, "auth.session_ttl_changed"))[0]
    assert first.details["other_sessions_shortened"] == 1


async def test_csrf_cookie_lives_as_long_as_the_session(app: FastAPI, owner: User) -> None:
    async with make_client(app) as anonymous:
        resp = await anonymous.get("/api/v1/auth/csrf")
        assert _max_age(resp, "moloko_csrf") == 168 * 3600
    async with logged_in_client(app) as client:
        assert (await _put(client, 24)).status_code == 200
        resp = await client.get("/api/v1/auth/csrf")
        assert 24 * 3600 - 60 <= _max_age(resp, "moloko_csrf") <= 24 * 3600


# --- refusals ------------------------------------------------------------------------


async def test_wrong_password_is_refused_and_audited(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        resp = await _put(client, 24, password="not-my-password-123")
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "invalid_password"
        assert "not-my-password-123" not in resp.text
        # The session is fine: no sign-out, nothing changed.
        assert (await client.get("/api/v1/auth/me")).status_code == 200
        assert _expires_in(await _session_of(app, client), 168)
    assert (await _user(app)).session_ttl_hours is None
    assert await _audit(app, "auth.session_ttl_changed") == []

    (failed,) = await _audit(app, "auth.password_confirm_failed")
    assert failed.outcome == "failure"
    assert failed.actor_type == "user" and failed.actor_id == owner.id
    assert failed.user_id == owner.id
    assert failed.details == {
        "subject_key": login_subject_key(OWNER_USERNAME),
        "reason": "bad_password",
        "purpose": "session_ttl",
    }


async def test_wrong_passwords_count_toward_the_login_lockout(
    app_factory: AppFactory, owner: User
) -> None:
    app = await app_factory(login_max_failures=3, login_lockout_seconds=60)
    async with logged_in_client(app) as client, make_client(app) as other:
        # Failures at login and here add up: 1 failed login + 2 wrong confirmations.
        assert (await login(other, password="wrong")).status_code == 401
        for _ in range(2):
            assert (await _put(client, 24, password="wrong")).status_code == 403

        blocked = await _put(client, 24)  # even the right password is refused now
        assert blocked.status_code == 429
        assert blocked.json()["error"]["code"] == "too_many_attempts"
        assert blocked.headers["retry-after"] == "60"
        # ...and so is signing in, exactly like after failed logins.
        locked_login = await login(other)
        assert locked_login.status_code == 429
        assert locked_login.json()["error"]["code"] == "too_many_attempts"
        assert (await client.get("/api/v1/auth/me")).status_code == 200

    assert (await _user(app)).session_ttl_hours is None
    (denied,) = await _audit(app, "auth.password_confirm_blocked")
    assert denied.outcome == "denied" and denied.user_id == owner.id
    assert len(await _audit(app, "auth.login_blocked")) == 1


async def test_correct_password_restarts_the_failure_count(
    app_factory: AppFactory, owner: User
) -> None:
    app = await app_factory(login_max_failures=3)
    async with logged_in_client(app) as client:
        for _ in range(2):
            assert (await _put(client, 24, password="wrong")).status_code == 403
        assert (await _put(client, 24)).status_code == 200
        for _ in range(2):
            assert (await _put(client, 24, password="wrong")).status_code == 403
        assert (await _put(client, 48)).status_code == 200


@pytest.mark.parametrize("ttl_hours", [0, -1, 2161, 10**12])
async def test_out_of_bounds_is_422(app: FastAPI, owner: User, ttl_hours: int) -> None:
    async with logged_in_client(app) as client:
        resp = await _put(client, ttl_hours)
        assert resp.status_code == 422
        error = resp.json()["error"]
        assert error["code"] == "session_ttl_out_of_range"
        assert error["details"] == {"field": "ttl_hours", "min": 1, "max": 2160}
    # Rejected before the password is checked: no attempt used, nothing changed.
    assert await _audit(app, "auth.password_confirm_failed") == []
    assert (await _user(app)).session_ttl_hours is None


@pytest.mark.parametrize(
    "body",
    [
        {"ttl_hours": "24", "password": OWNER_PASSWORD},
        {"ttl_hours": 1.5, "password": OWNER_PASSWORD},
        {"ttl_hours": True, "password": OWNER_PASSWORD},
        {"password": OWNER_PASSWORD},
        {"ttl_hours": 24},
        {"ttl_hours": 24, "password": ""},
        {"ttl_hours": 24, "password": OWNER_PASSWORD, "extra": 1},
    ],
)
async def test_malformed_body_is_422(app: FastAPI, owner: User, body: dict[str, Any]) -> None:
    async with logged_in_client(app) as client:
        resp = await client.put(URL, json=body, headers=await csrf_headers(client))
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"
    assert OWNER_PASSWORD not in resp.text


async def test_requires_a_session(client: httpx.AsyncClient, owner: User) -> None:
    assert (await client.get(URL)).status_code == 401
    resp = await _put(client, 24)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "not_authenticated"


async def test_requires_csrf(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        resp = await client.put(URL, json={"ttl_hours": 24, "password": OWNER_PASSWORD})
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "csrf_failed"
    assert (await _user(app)).session_ttl_hours is None
    assert await _audit(app, "auth.password_confirm_failed") == []
