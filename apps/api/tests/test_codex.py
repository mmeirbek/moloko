"""Codex with the owner's ChatGPT sign-in (owner's decision 2026-11-04): the `codex` service
runs OpenAI's Codex CLI for agents' tasks; an agent whose model is a Codex model has its task
done by Codex, step by step in the task's chat."""

from __future__ import annotations

import json
import stat
import threading
import uuid
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.codex import client as codex_client
from app.codex_service import server
from app.models import Task, User
from app.models.agent import AgentRun
from app.models.event import AgentEvent
from tests.conftest import (
    OWNER_PASSWORD,
    OWNER_USERNAME,
    AppFactory,
    RecordingQueue,
    csrf_headers,
    drain,
    logged_in_client,
    run_agent,
)


def _line(event: dict[str, Any]) -> str:
    return "echo '" + json.dumps(event, separators=(",", ":")) + "'"


MODELS = {
    "models": [
        {"slug": "gpt-6-sol", "display_name": "GPT-6 Sol", "visibility": "list"},
        {"slug": "hidden", "visibility": "hide"},
    ]
}
COMMAND = {
    "id": "1",
    "type": "command_execution",
    "command": "ls",
    "aggregated_output": "a.py",
    "exit_code": 0,
    "status": "completed",
}
USAGE = {"input_tokens": 120, "output_tokens": 30, "reasoning_output_tokens": 5}
# A stand-in for the codex binary: records its arguments and stdin, prints JSON Lines.
FAKE_CODEX = "\n".join(
    [
        "#!/bin/sh",
        'printf \'%s\\n\' "$@" > "$CODEX_FAKE_DIR/args"',
        'cat > "$CODEX_FAKE_DIR/stdin"',
        'case "$1" in',
        '  login) echo "Logged in using ChatGPT" >&2; exit 0 ;;',
        '  --version) echo "codex-cli 0.166.0"; exit 0 ;;',
        f"  debug) {_line(MODELS)}; exit 0 ;;",
        "esac",
        _line({"type": "thread.started", "thread_id": "th-1"}),
        _line({"type": "item.completed", "item": COMMAND}),
        _line(
            {"type": "item.completed", "item": {"id": "2", "type": "agent_message", "text": "ok"}}
        ),
        _line({"type": "turn.completed", "usage": USAGE}),
        'echo "warning sk-secret1234567890 stays hidden" >&2',
        "",
    ]
)


@pytest.fixture
def codex_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    fake = tmp_path / "codex"
    fake.write_text(FAKE_CODEX)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "ws" / "task1").mkdir(parents=True)
    monkeypatch.setenv("CODEX_FAKE_DIR", str(tmp_path))
    monkeypatch.setattr(server, "CODEX", str(fake))
    monkeypatch.setattr(server, "WORKSPACES", (tmp_path / "ws").resolve())
    monkeypatch.setattr(server, "TOKEN", "secret-token")
    monkeypatch.setattr(server, "GITHUB_FILE", tmp_path / "home" / "moloko-github.json")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_the_service_runs_codex_and_streams_its_events(codex_server: str, tmp_path: Path) -> None:
    auth = {"Authorization": "Bearer secret-token"}
    assert httpx.get(f"{codex_server}/v1/health").json() == {"ok": True}
    assert httpx.get(f"{codex_server}/v1/status").status_code == 401  # the token is required
    status = httpx.get(f"{codex_server}/v1/status", headers=auth).json()
    assert status == {"logged_in": True, "mode": "chatgpt", "version": "codex-cli 0.166.0"}
    assert httpx.get(f"{codex_server}/v1/models", headers=auth).json() == [
        {"id": "gpt-6-sol", "name": "GPT-6 Sol"}  # hidden models are left out
    ]
    escape = httpx.post(
        f"{codex_server}/v1/run", headers=auth, json={"cwd": "../..", "prompt": "x"}
    )
    assert escape.status_code == 400  # only folders of the workspaces

    resp = httpx.post(
        f"{codex_server}/v1/run",
        headers=auth,
        json={"cwd": "task1", "prompt": "Fix it", "model": "gpt-6-sol", "thread_id": "th-0"},
    )
    events = [json.loads(line) for line in resp.text.splitlines()]
    assert [e["type"] for e in events] == [
        "thread.started",
        "item.completed",
        "item.completed",
        "turn.completed",
        "moloko.exit",
    ]
    assert events[-1]["code"] == 0
    assert "sk-secret" not in events[-1]["stderr"] and "[redacted]" in events[-1]["stderr"]
    args = (tmp_path / "args").read_text().split("\n")
    assert args[:2] == ["exec", "--json"]
    assert "--dangerously-bypass-approvals-and-sandbox" in args
    assert args[args.index("-C") + 1] == str((tmp_path / "ws" / "task1").resolve())
    assert args[args.index("-m") + 1] == "gpt-6-sol"
    assert args[args.index("resume") + 1] == "th-0" and args[-2] == "-"
    assert (tmp_path / "stdin").read_text() == "Fix it"


def _fake_service(
    runs: list[dict[str, Any]],
    replies: list[list[dict[str, Any]]],
    github: list[dict[str, Any]] | None = None,
) -> Any:
    github = github if github is not None else []

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.headers["authorization"] == "Bearer t"
        if request.url.path == "/v1/models":
            return httpx2.Response(200, json=[{"id": "gpt-6-sol", "name": "GPT-6 Sol"}])
        if request.url.path == "/v1/github":
            github.append(json.loads(request.content))
            return httpx2.Response(200, json={"ok": True, "github": True})
        if request.url.path == "/v1/status":
            return httpx2.Response(200, json={"logged_in": True, "mode": "chatgpt", "version": "v"})
        runs.append(json.loads(request.content))
        events = replies[min(len(runs) - 1, len(replies) - 1)]
        body = "".join(json.dumps(e) + "\n" for e in events)
        return httpx2.Response(200, text=body, headers={"content-type": "application/x-ndjson"})

    return httpx2.MockTransport(handler)


DONE = "Готово: тесты проходят."
TURN: list[dict[str, Any]] = [
    {"type": "thread.started", "thread_id": "th-9"},
    {
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "command": "pytest -q",
            "aggregated_output": "3 passed",
            "exit_code": 0,
            "status": "completed",
        },
    },
    {
        "type": "item.completed",
        "item": {
            "type": "file_change",
            "changes": [{"path": "a.py", "kind": "update"}],
            "status": "completed",
        },
    },
    {
        "type": "item.completed",
        "item": {"type": "agent_message", "text": "Готово: тесты проходят."},
    },
    {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20}},
    {"type": "moloko.exit", "code": 0, "stderr": ""},
]


async def _codex_app(
    app_factory: AppFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, transport: Any
) -> FastAPI:
    from app.services.users import UserService

    original = codex_client.CodexClient.__init__

    def with_transport(self: Any, settings: Any, transport_: Any = None) -> None:
        original(self, settings, transport)

    monkeypatch.setattr(codex_client.CodexClient, "__init__", with_transport)
    app = await app_factory(
        codex_url="http://codex.test", codex_service_token="t", workspace_root=str(tmp_path / "ws")
    )
    async with app.state.db.sessionmaker() as db:
        await UserService(db).create_owner(OWNER_USERNAME, OWNER_PASSWORD, "Owner")
    app.state.queue = RecordingQueue()
    return app


async def _codex_agent(client: httpx.AsyncClient) -> dict[str, Any]:
    headers = await csrf_headers(client)
    provider = await client.post(
        "/api/v1/providers", json={"kind": "codex", "name": "Codex (ChatGPT)"}, headers=headers
    )
    assert provider.status_code == 201, provider.text
    assert provider.json()["api_key_source"] == "environment"  # signed in on the server
    synced = await client.post(
        f"/api/v1/providers/{provider.json()['id']}/sync-models", headers=headers
    )
    assert synced.json()["added"] == 1, synced.text
    models = (await client.get("/api/v1/models")).json()
    codex_model = next(m for m in models if m["provider_kind"] == "codex")
    agent = await client.post(
        "/api/v1/agents",
        json={"name": "Кодер", "model_config_id": codex_model["id"]},
        headers=headers,
    )
    assert agent.status_code == 201, agent.text
    return dict(agent.json())


async def test_an_agent_with_a_codex_model_has_its_task_done_by_codex(
    app_factory: AppFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs: list[dict[str, Any]] = []
    app = await _codex_app(app_factory, tmp_path, monkeypatch, _fake_service(runs, [TURN]))
    async with logged_in_client(app) as client:
        status = (await client.get("/api/v1/codex/status")).json()
        assert status["logged_in"] and status["mode"] == "chatgpt"
        assert "codex login --device-auth" in status["login_command"]
        assert "codex" in (await client.get("/api/v1/providers/kinds")).json()
        agent = await _codex_agent(client)
        task_id = (await run_agent(client, agent["id"], "Почини тесты")).json()["task"]["id"]
        await drain(app, app.state.queue)

    async with app.state.db.sessionmaker() as db:
        task = await db.get(Task, uuid.UUID(task_id))
        assert task is not None and task.run_id is not None
        run = await db.get(AgentRun, task.run_id)
        assert run is not None
        types = [
            (e.type, e.payload.get("kind"))
            for e in (
                await db.execute(
                    select(AgentEvent).where(AgentEvent.task_id == task.id).order_by(AgentEvent.seq)
                )
            ).scalars()
            if e.type in ("agent.codex_step", "agent.message")
        ]
    assert task.status == "completed" and task.result == DONE
    assert types == [
        ("agent.codex_step", "command"),
        ("agent.codex_step", "files"),
        ("agent.message", None),
    ]
    assert run.state["codex_thread_id"] == "th-9"
    assert run.usage["input_tokens"] == 100 and run.usage["output_tokens"] == 20
    assert task.progress > 0
    [call] = runs
    assert call["model"] == "gpt-6-sol" and call["thread_id"] is None
    assert call["cwd"] and "Почини тесты" in call["prompt"]
    assert (tmp_path / "ws" / call["cwd"]).is_dir()  # the task's own workspace


async def test_the_owners_note_continues_the_codex_thread_and_a_plan_limit_is_named(
    app_factory: AppFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs: list[dict[str, Any]] = []
    limit: list[dict[str, Any]] = [
        {"type": "thread.started", "thread_id": "th-9"},
        {"type": "turn.failed", "error": {"message": "You've hit your usage limit."}},
        {"type": "moloko.exit", "code": 1, "stderr": ""},
    ]
    app = await _codex_app(app_factory, tmp_path, monkeypatch, _fake_service(runs, [TURN, limit]))
    async with logged_in_client(app) as client:
        agent = await _codex_agent(client)
        task_id = (await run_agent(client, agent["id"], "Почини тесты")).json()["task"]["id"]
        # written before the first turn ends: Codex goes on in the same thread with it
        resp = await client.post(
            f"/api/v1/tasks/{task_id}/message",
            json={"text": "И обнови README"},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 200, resp.text
        await drain(app, app.state.queue)
    async with app.state.db.sessionmaker() as db:
        task = await db.get(Task, uuid.UUID(task_id))
        assert task is not None
    assert len(runs) == 2
    assert runs[1]["thread_id"] == "th-9" and "И обнови README" in runs[1]["prompt"]
    # the second turn hit the ChatGPT plan's limit: said honestly
    assert (task.status, task.error_code) == ("failed", "provider_rate_limited")


async def test_a_codex_model_answers_in_the_chat_too(
    app_factory: AppFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The owner's default model was a Codex model, and the chat refused it."""
    from app.providers.base import ChatMessage, ChatRequest
    from app.providers.codex_provider import CHAT_FOLDER, CodexProvider

    runs: list[dict[str, Any]] = []
    app = await _codex_app(app_factory, tmp_path, monkeypatch, _fake_service(runs, [TURN]))
    chunks = [
        c
        async for c in CodexProvider(app.state.settings).stream(
            ChatRequest(
                model="gpt-6-sol",
                system="You are moloko.",
                messages=(
                    ChatMessage(role="user", content="Привет"),
                    ChatMessage(role="assistant", content="Здравствуйте!"),
                    ChatMessage(role="user", content="Сколько тестов?"),
                ),
            )
        )
    ]
    assert [c.text for c in chunks[:-1]] == [DONE]
    final = chunks[-1].result
    assert final is not None and final.text == DONE and final.usage.input_tokens == 100
    [call] = runs
    assert call["cwd"] == CHAT_FOLDER and call["wait_seconds"] == 90
    assert call["prompt"].index("Привет") < call["prompt"].index("Сколько тестов?")
    assert "You are moloko." in call["prompt"]
    assert (tmp_path / "ws" / CHAT_FOLDER).is_dir()


def test_a_text_only_model_gets_the_chat_without_its_pictures() -> None:
    from app.providers.base import ChatMessage, ChatRequest, ImagePart
    from app.providers.openai_provider import without_images

    req = ChatRequest(
        model="openai/gpt-oss-120b",
        messages=(
            ChatMessage(
                role="user",
                content="Что на фото?",
                images=(ImagePart(media_type="image/png", data_b64="AAAA"),),
            ),
        ),
    )
    plain = without_images(req)
    assert plain.messages[0].images == ()
    assert plain.messages[0].content.startswith("Что на фото?")
    assert "1 picture(s)" in plain.messages[0].content


async def _owner(app: FastAPI) -> User | None:
    async with app.state.db.sessionmaker() as db:
        return (await db.execute(select(User))).scalar_one_or_none()


def test_codex_runs_with_the_owners_github_access(codex_server: str, tmp_path: Path) -> None:
    """Saved GitHub access: Codex's git and gh act as the owner; the token never shows."""
    auth = {"Authorization": "Bearer secret-token"}
    token = "github_pat_" + "y" * 40
    saved = httpx.put(
        f"{codex_server}/v1/github", headers=auth, json={"token": token, "login": "meirbek"}
    )
    assert saved.json() == {"ok": True, "github": True}
    assert oct(server.GITHUB_FILE.stat().st_mode & 0o777) == "0o600"
    env = server.run_env()
    assert env["GH_TOKEN"] == token and env["GITHUB_TOKEN"] == token
    config = {
        env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"]
        for i in range(int(env["GIT_CONFIG_COUNT"]))
    }
    assert "x-access-token" in config["credential.https://github.com.helper"]
    assert config["user.name"] == "meirbek"
    assert config["user.email"] == "meirbek@users.noreply.github.com"
    assert "CODEX_SERVICE_TOKEN" not in env
    assert token not in server.redact(f"fatal: {token} rejected")
    # taken away again
    httpx.put(f"{codex_server}/v1/github", headers=auth, json={"token": None})
    assert "GH_TOKEN" not in server.run_env() and not server.GITHUB_FILE.exists()


async def test_saving_the_github_token_gives_it_to_codex(
    app_factory: AppFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.integrations import github as gh
    from tests.test_tools_integrations import github_mock

    sent: list[dict[str, Any]] = []
    app = await _codex_app(app_factory, tmp_path, monkeypatch, _fake_service([], [TURN], sent))
    monkeypatch.setattr(gh, "TRANSPORT", github_mock([]))
    token = "github_pat_" + "z" * 40
    async with logged_in_client(app) as client:
        headers = await csrf_headers(client)
        resp = await client.put(
            "/api/v1/integrations/github", json={"token": token}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        assert sent[-1] == {"token": token, "login": "owner"}
        await client.put("/api/v1/integrations/github", json={"enabled": False}, headers=headers)
    assert sent[-1] == {"token": None, "login": None}  # switched off: Codex loses it
