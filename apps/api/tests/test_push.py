"""Web Push: RFC 8291 encryption, VAPID, subscriptions, and the event dispatcher."""

from __future__ import annotations

import json
import struct
import uuid
from typing import Any

import httpx2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import FastAPI
from sqlalchemy import select

from app.events import bus
from app.models import PushSubscription
from app.push import webpush
from app.push.dispatcher import dispatch
from app.push.webpush import VapidKeys, b64u, b64u_decode, public_bytes
from tests.conftest import AppFactory, csrf_headers, logged_in_client

ENDPOINT = "https://fcm.googleapis.com/fcm/send/device-1"


class Browser:
    """The receiving side of a push subscription (what a browser does)."""

    def __init__(self) -> None:
        self.private = ec.generate_private_key(ec.SECP256R1())
        self.auth = b"0123456789abcdef"

    @property
    def keys(self) -> dict[str, str]:
        return {"p256dh": b64u(public_bytes(self.private.public_key())), "auth": b64u(self.auth)}

    def decrypt(self, body: bytes) -> bytes:
        salt, rs, idlen = body[:16], struct.unpack("!I", body[16:20])[0], body[20]
        as_public = body[21 : 21 + idlen]
        ciphertext = body[21 + idlen :]
        assert rs == 4096
        shared = self.private.exchange(
            ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public)
        )
        ua_public = public_bytes(self.private.public_key())

        def hkdf(salt_: bytes, info: bytes, n: int, ikm: bytes) -> bytes:
            return HKDF(algorithm=hashes.SHA256(), length=n, salt=salt_, info=info).derive(ikm)

        ikm = hkdf(self.auth, b"WebPush: info\x00" + ua_public + as_public, 32, shared)
        cek = hkdf(salt, b"Content-Encoding: aes128gcm\x00", 16, ikm)
        nonce = hkdf(salt, b"Content-Encoding: nonce\x00", 12, ikm)
        record = AESGCM(cek).decrypt(nonce, ciphertext, None)
        assert record.endswith(b"\x02")
        return record[:-1]


def test_encryption_round_trip() -> None:
    browser = Browser()
    body = webpush.encrypt(b'{"title":"hi"}', **browser.keys)
    assert browser.decrypt(body) == b'{"title":"hi"}'


def test_vapid_header_is_a_valid_es256_jwt() -> None:
    keys = VapidKeys.generate()
    header = keys.authorization("https://web.push.apple.com/abc", "mailto:me@example.org")
    token, k = header.removeprefix("vapid t=").split(", k=")
    assert k == keys.public_b64
    head, claims, signature = token.split(".")
    raw = b64u_decode(signature)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    keys.private.public_key().verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))
    body = json.loads(b64u_decode(claims))
    assert body["aud"] == "https://web.push.apple.com" and body["sub"] == "mailto:me@example.org"
    assert VapidKeys.from_pem(keys.pem()).public_b64 == keys.public_b64


@pytest.mark.parametrize(
    ("endpoint", "ok"),
    [
        ("https://fcm.googleapis.com/fcm/send/x", True),
        ("https://updates.push.services.mozilla.com/wpush/v2/x", True),
        ("https://web.push.apple.com/x", True),
        ("https://db5p.notify.windows.com/w/?token=x", True),
        ("http://fcm.googleapis.com/x", False),
        ("https://evil.example/x", False),
        ("https://fcm.googleapis.com.evil.example/x", False),
    ],
)
def test_only_known_push_services(endpoint: str, ok: bool) -> None:
    from tests.conftest import make_settings

    assert webpush.host_allowed(endpoint, make_settings().push_allowed_hosts) is ok


@pytest.fixture
async def push_app(app_factory: AppFactory) -> FastAPI:
    from app.services.users import UserService
    from tests.conftest import OWNER_PASSWORD, OWNER_USERNAME

    app = await app_factory(app_encryption_key="k" * 44)
    async with app.state.db.sessionmaker() as db:
        await UserService(db).create_owner(OWNER_USERNAME, OWNER_PASSWORD, "Owner")
    return app


async def emit(app: FastAPI, user_id: uuid.UUID, type_: str, payload: dict[str, Any]) -> None:
    async with app.state.db.sessionmaker() as db:
        await bus.emit(db, user_id=user_id, type=type_, payload=payload)
        await bus.commit(db)


async def test_subscribe_and_receive_pushes_for_new_events(
    push_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    browser = Browser()
    received: list[httpx2.Request] = []
    gone = {"value": False}

    def handler(request: httpx2.Request) -> httpx2.Response:
        received.append(request)
        return httpx2.Response(410 if gone["value"] else 201)

    monkeypatch.setattr(webpush, "TRANSPORT", httpx2.MockTransport(handler))
    async with logged_in_client(push_app) as client:
        key = (await client.get("/api/v1/push/key")).json()["public_key"]
        assert key == (await client.get("/api/v1/push/key")).json()["public_key"]  # stable
        bad = await client.post(
            "/api/v1/push/subscriptions",
            json={"endpoint": "https://evil.example/x", "keys": browser.keys},
            headers=await csrf_headers(client),
        )
        assert bad.status_code == 422
        resp = await client.post(
            "/api/v1/push/subscriptions",
            json={
                "endpoint": ENDPOINT,
                "keys": browser.keys,
                "kinds": ["approval", "taskDone"],
                "label": "Phone",
            },
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 200, resp.text
        me = (await client.get("/api/v1/auth/me")).json()["user"]["id"]
    user_id = uuid.UUID(me)
    sessionmaker = push_app.state.db.sessionmaker
    settings = push_app.state.settings

    await emit(
        push_app,
        user_id,
        "task.completed",
        {"task": {"id": "old", "title": "Before", "parent_task_id": None}},
    )
    assert await dispatch(sessionmaker, settings) == 0  # first run: start from now, no backlog

    await emit(
        push_app,
        user_id,
        "approval.required",
        {"approval": {"id": "a1", "summary": "Delete x", "agent_name": "Dev"}},
    )
    await emit(
        push_app,
        user_id,
        "task.completed",
        {"task": {"id": "t1", "title": "Report", "parent_task_id": None}},
    )
    await emit(
        push_app,
        user_id,
        "task.completed",
        {"task": {"id": "s1", "title": "Part", "parent_task_id": "t1"}},
    )
    await emit(
        push_app,
        user_id,
        "task.failed",
        {"task": {"id": "t2", "title": "Oops", "parent_task_id": None}},
    )
    await emit(push_app, user_id, "agent.status_changed", {})
    assert (
        await dispatch(sessionmaker, settings) == 2
    )  # approval + done; no subtask, no taskFailed (not chosen)
    messages = [json.loads(browser.decrypt(r.content)) for r in received]
    assert messages == [
        {
            "title": "Нужно ваше одобрение",
            "body": "Dev: Delete x",
            "url": "/approvals",
            "tag": "approval:a1",
        },
        {
            "title": "Задача выполнена",
            "body": "Report",
            "url": "/tasks/t1",
            "tag": "task:t1:task.completed",
        },
    ]
    first = received[0]
    assert (
        first.headers["authorization"].startswith("vapid t=")
        and first.headers["content-encoding"] == "aes128gcm"
    )
    assert first.headers["urgency"] == "high" and first.headers["ttl"] == str(
        settings.push_ttl_seconds
    )
    assert await dispatch(sessionmaker, settings) == 0  # never twice

    gone["value"] = True  # the browser dropped the subscription
    await emit(
        push_app,
        user_id,
        "task.completed",
        {"task": {"id": "t3", "title": "Again", "parent_task_id": None}},
    )
    await dispatch(sessionmaker, settings)
    async with sessionmaker() as db:
        assert (await db.execute(select(PushSubscription))).scalars().all() == []


async def test_push_needs_an_encryption_key(app_factory: AppFactory) -> None:
    from app.services.users import UserService
    from tests.conftest import OWNER_PASSWORD, OWNER_USERNAME

    app = await app_factory(app_encryption_key=None)
    async with app.state.db.sessionmaker() as db:
        await UserService(db).create_owner(OWNER_USERNAME, OWNER_PASSWORD, "Owner")
    async with logged_in_client(app) as client:
        resp = await client.get("/api/v1/push/key")
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "push_unavailable"


def test_notice_rules_match_the_in_app_notifications() -> None:
    from datetime import UTC, datetime, timedelta

    from app.models.event import AgentEvent
    from app.push.dispatcher import MAX_AGE, notice_for

    now = datetime.now(UTC)

    def event(type_: str, payload: dict[str, Any], age: timedelta = timedelta()) -> AgentEvent:
        return AgentEvent(type=type_, payload=payload, created_at=now - age, user_id=uuid.uuid4())

    top = {"task": {"id": "t1", "title": "Report", "parent_task_id": None}}
    done = notice_for(event("task.completed", top), now)
    assert done is not None and done.kind == "taskDone" and done.url == "/tasks/t1"
    failed = notice_for(event("task.failed", top), now)
    assert failed is not None and failed.kind == "taskFailed"
    # subtasks are part of a bigger job; stale events (replayed after downtime) are skipped
    sub = {"task": {"id": "t2", "title": "Part", "parent_task_id": "t1"}}
    assert notice_for(event("task.completed", sub), now) is None
    assert notice_for(event("task.completed", top, MAX_AGE + timedelta(seconds=1)), now) is None
    approval = {"approval": {"id": "a1", "agent_name": "Ana", "summary": "Write a.txt"}}
    need = notice_for(event("approval.required", approval), now)
    assert need is not None and need.kind == "approval" and need.subject == "Ana: Write a.txt"
    assert notice_for(event("agent.status_changed", {}), now) is None
