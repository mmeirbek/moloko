"""Web Push: RFC 8291 encryption, VAPID, subscriptions, and the event dispatcher."""

from __future__ import annotations

import json
import struct
import uuid
from dataclasses import replace
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
        {
            "task": {
                "id": "t1",
                "title": "Report",
                "parent_task_id": None,
                "result": "## Итог\n\n**Готово**: отчёт в report.md.",
            }
        },
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
            "title": "Dev ждёт вашего одобрения",
            "body": "Delete x",
            "url": "/approvals",
            "tag": "approval:a1",
        },
        {
            "title": "Готово: Report",
            "body": "Готово: отчёт в report.md.",
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
    assert need is not None and need.kind == "approval" and need.name == "Ana"
    assert notice_for(event("agent.status_changed", {}), now) is None


def test_notifications_are_plain_words_not_code() -> None:
    from app.push.dispatcher import Notice, render

    def approval(tool: str, args: dict[str, Any], task: str = "t1") -> Notice:
        return Notice(
            "approval",
            "approval:x",
            "raw",
            "/approvals",
            name="Кодер король",
            tool=tool,
            args=args,
            tag=f"approval:task:{task}",
        )

    script = 'python3 -c "\ndef L(h):\n  c=[int(h[i:i+2],16)/255 for i in (1,3,5)]\n"'
    assert render(approval("terminal_run", {"command": script}), "ru") == (
        "Кодер король ждёт вашего одобрения",
        "Выполнить команду python3",
    )
    assert render(approval("terminal_run", {"command": "cd /w && npm i"}), "ru")[1] == (
        "Выполнить команду cd"
    )
    path = "moloko-mobile-polish/apps/web/app/(app)/chat/layout.tsx"
    assert render(approval("fs_write", {"path": path, "content": "x" * 900}), "ru")[1] == (
        "Записать файл layout.tsx"
    )
    gh = {"repo": "mmeirbek/moloko", "path": "apps/web/page-header.tsx", "content": "…"}
    assert render(approval("github_write_file", gh), "ru")[1] == (
        "Сохранить файл page-header.tsx в GitHub (mmeirbek/moloko)"
    )
    assert render(approval("terminal_run", {"command": "ls"}), "en") == (
        "Кодер король needs your approval",
        "Run a ls command",
    )
    assert render(approval("some_mcp_tool", {"q": "x"}), "ru")[1] == "Действие: some mcp tool"

    long_title = (
        "Найди репозитории молоко на гитхабе, надо улучшить фронтенд дизайн для телефонов " * 3
    )
    failed = Notice(
        "taskFailed",
        "k",
        long_title + "```py\nprint(1)\n```",
        "/tasks/t",
        name="Кодер король",
        error_code="empty_result",
    )
    title, body = render(failed, "ru")
    assert title.startswith("Сломалось: Найди репозитории") and title.endswith("…")
    assert len(title) < 80 and "```" not in title
    assert body == "Кодер король: агент закончил без результата"
    done = Notice("taskDone", "k", "[[mock:sleep:1]] Отчёт", "/tasks/t")
    assert render(done, "ru") == ("Готово: Отчёт", "")
    assert render(Notice("taskDone", "k", "", "/tasks/t"), "en") == ("Task done", "")


def test_a_finished_task_says_its_short_result_or_the_question_it_asks() -> None:
    from datetime import UTC, datetime

    from app.models.event import AgentEvent
    from app.push.dispatcher import notice_for, render

    now = datetime.now(UTC)

    def finished(result: str) -> tuple[str, str]:
        task = {"id": "t1", "title": "Сайт", "parent_task_id": None, "result": result}
        event = AgentEvent(
            type="task.completed", payload={"task": task}, created_at=now, user_id=uuid.uuid4()
        )
        notice = notice_for(event, now)
        assert notice is not None and notice.kind == "taskDone"  # same switch as «готово»
        return render(replace(notice, name="Оркестратор"), "ru")

    long = "Сделал: " + "проверил страницы, " * 30 + "всё работает."
    title, body = finished(long + "\n\n```sh\nnpm test\n```")
    assert title == "Готово: Сайт" and body.startswith("Оркестратор: Сделал: проверил")
    assert body.endswith("…") and len(body) < 230 and "npm" not in body
    assert finished("Нашёл два сайта.\n\n**Уточните, какой из них нужен?**") == (
        "Оркестратор ждёт вашего ответа",
        "Уточните, какой из них нужен?",
    )
    assert finished("Что сделать? Всё готово.")[0] == "Готово: Сайт"


def test_only_a_used_up_budget_is_announced() -> None:
    from datetime import UTC, datetime

    from app.models.event import AgentEvent
    from app.push.dispatcher import notice_for, render

    now = datetime.now(UTC)

    def warning(percent: int) -> AgentEvent:
        payload = {"percent": percent, "month": "2026-11", "spent_usd": "5", "limit_usd": "5"}
        return AgentEvent(
            type="budget.warning", payload=payload, created_at=now, user_id=uuid.uuid4()
        )

    assert notice_for(warning(80), now) is None
    used_up = notice_for(warning(100), now)
    assert used_up is not None
    assert render(used_up, "ru") == ("Месячный лимит расходов исчерпан", "$5 / $5")


def test_repository_and_package_actions_in_plain_words() -> None:
    from app.push.texts import approval_text

    online = {"command": "npm ci --prefix moloko", "network": "packages"}
    assert approval_text("ru", "terminal_run", online) == "Выполнить npm и скачать пакеты"
    assert approval_text("en", "terminal_run", online) == "Run npm with package downloads"
    assert approval_text("ru", "terminal_run", {"command": "npm ci"}) == "Выполнить команду npm"
    checkout = {"repo": "mmeirbek/moloko", "ref": "main"}
    assert (
        approval_text("ru", "github_checkout", checkout)
        == "Скачать mmeirbek/moloko в рабочую папку"
    )
    commit = {"repo": "mmeirbek/moloko", "branch": "feature/ui", "paths": ["a/b.tsx"] * 40}
    assert approval_text("ru", "github_commit_files", commit) == (
        "Сохранить файлы в GitHub (mmeirbek/moloko, feature/ui)"
    )
    assert approval_text("en", "github_commit_files", commit) == (
        "Commit files to GitHub (mmeirbek/moloko, feature/ui)"
    )


def test_the_push_contact_is_never_a_placeholder_apple_refuses() -> None:
    from app.push.webpush import push_subject

    site = ["https://moloko.tail1234.ts.net"]
    assert push_subject("mailto:owner@moloko.invalid", site) == "https://moloko.tail1234.ts.net"
    assert push_subject("mailto:admin@localhost", [*site, "x"]) == site[0]
    assert push_subject("mailto:me@example.org", site) == site[0]
    assert push_subject("mailto:me@mail.kz", site) == "mailto:me@mail.kz"
    assert push_subject("https://my.site/", site) == "https://my.site/"
    # nothing better known: keep what was configured
    assert push_subject("mailto:owner@moloko.invalid", []) == "mailto:owner@moloko.invalid"
    assert push_subject("mailto:owner@moloko.invalid", ["http://127.0.0.1:3000"]).endswith(
        ".invalid"
    )
