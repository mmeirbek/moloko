"""The `codex` service: OpenAI's official Codex CLI, signed in with the owner's ChatGPT account
(owner's decision 2026-11-04: Codex with the ChatGPT sign-in), run for agents'
tasks. Only the backend and the worker reach it (their own network, a shared token); the owner
signs in once inside the container: ``docker compose exec codex codex login --device-auth``.

The container is the sandbox (no docker socket, no database, only the agents' workspaces and
its own home with ``auth.json``), so Codex runs with its own sandbox off. One run at a time:
OpenAI says one ``auth.json`` must not serve concurrent jobs. Standard library only — this file
is copied into the image as it is (infrastructure/docker/codex.Dockerfile).

API (all but /v1/health need ``Authorization: Bearer $CODEX_SERVICE_TOKEN``):
  GET  /v1/health  → {"ok": true}
  GET  /v1/status  → {"logged_in": bool, "mode": "chatgpt"|"api_key"|null, "version": str}
  GET  /v1/models  → [{"id": "...", "name": "..."}]   (the signed-in account's models)
  PUT  /v1/github  {"token": "..."|null, "login": "..."|null} — the owner's GitHub access for
                   Codex's git and gh (kept in its home next to the sign-in; null = remove)
  POST /v1/run     {"cwd": "<dir under the workspaces>", "prompt": "...", "model": "..."|null,
                    "thread_id": "..."|null, "wait_seconds": N|null}  (409 if busy longer)
                   → JSON Lines: Codex's own events (`codex exec --json`), then
                     {"type": "moloko.exit", "code": N, "stderr": "<last lines>"}
"""

from __future__ import annotations

import contextlib
import hmac
import json
import os
import re
import signal
import subprocess
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

CODEX = os.environ.get("CODEX_BIN", "codex")
WORKSPACES = Path(os.environ.get("CODEX_WORKSPACES", "/data/workspaces")).resolve()
TOKEN = os.environ.get("CODEX_SERVICE_TOKEN", "")
TIMEOUT = int(os.environ.get("CODEX_RUN_TIMEOUT_SECONDS", "3600"))
QUEUE_WAIT = int(os.environ.get("CODEX_QUEUE_WAIT_SECONDS", "1800"))
MAX_BODY = 2_000_000
STDERR_KEEP = 2000

_one_at_a_time = threading.Lock()
# Never echo anything that looks like a credential back (stderr goes to the backend's logs).
_SECRET = re.compile(
    r"(sk-[A-Za-z0-9_-]{8,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_.-]+|Bearer\s+\S+"
    r"|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"
)
GITHUB_FILE = Path(os.environ.get("CODEX_HOME", "/codex-home")) / "moloko-github.json"


def redact(text: str) -> str:
    return _SECRET.sub("[redacted]", text)


def inside_workspaces(cwd: str) -> Path | None:
    """The run's folder: an existing directory under the workspaces volume, else None."""
    path = (WORKSPACES / cwd).resolve()
    if path != WORKSPACES and WORKSPACES not in path.parents:
        return None
    return path if path.is_dir() else None


def exec_command(model: str | None, thread_id: str | None, cwd: Path) -> list[str]:
    # exec's own options come before the `resume` subcommand
    cmd = [CODEX, "exec"]
    cmd += [
        "--json",
        "--skip-git-repo-check",
        # the container is the sandbox: Codex's own (bubblewrap) cannot nest inside it
        "--dangerously-bypass-approvals-and-sandbox",
        "-C",
        str(cwd),
    ]
    if model:
        cmd += ["-m", model]
    if thread_id:
        cmd += ["resume", thread_id]
    cmd.append("-")  # the prompt comes on stdin
    return cmd


def _codex(*args: str, timeout: int) -> subprocess.CompletedProcess[str]:
    """One short Codex command with fixed arguments (no input from requests)."""
    return subprocess.run(  # noqa: S603 — fixed program and arguments
        [CODEX, *args], capture_output=True, text=True, timeout=timeout, check=False
    )


def login_status() -> dict[str, Any]:
    try:
        done = _codex("login", "status", timeout=30)
        version = _codex("--version", timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return {"logged_in": False, "mode": None, "version": ""}
    said = (done.stdout + done.stderr).lower()
    mode = "chatgpt" if "chatgpt" in said else "api_key" if "api key" in said else None
    return {
        "logged_in": done.returncode == 0 and mode is not None,
        "mode": mode,
        "version": version,
    }


def list_models() -> list[dict[str, str]]:
    done = _codex("debug", "models", timeout=60)
    if done.returncode != 0:
        raise RuntimeError(redact(done.stderr.strip())[-300:] or "codex debug models failed")
    data = json.loads(done.stdout)
    models = data.get("models", data) if isinstance(data, dict) else data
    return [
        {"id": str(m["slug"]), "name": str(m.get("display_name") or m["slug"])}
        for m in models
        if isinstance(m, dict) and m.get("slug") and m.get("visibility", "list") == "list"
    ]


def save_github(token: str | None, login: str | None) -> bool:
    """Keep (or forget) the owner's GitHub token for Codex's runs; only this file has it."""
    if not token:
        GITHUB_FILE.unlink(missing_ok=True)
        return False
    GITHUB_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = GITHUB_FILE.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump({"token": token, "login": login or ""}, fh)
    tmp.replace(GITHUB_FILE)
    return True


def run_env() -> dict[str, str]:
    """Codex's environment: with the owner's GitHub token, git (over HTTPS) and gh act as the
    owner, and commits carry the owner's GitHub name."""
    env = dict(os.environ)
    env.pop("CODEX_SERVICE_TOKEN", None)  # Codex's commands never see the service's token
    try:
        saved = json.loads(GITHUB_FILE.read_text())
    except (OSError, ValueError):
        return env
    token, login = str(saved.get("token") or ""), str(saved.get("login") or "")
    if not token:
        return env
    helper = '!f() { echo username=x-access-token; echo "password=$GH_TOKEN"; }; f'
    config = [("credential.https://github.com.helper", helper)]
    if login:
        config += [("user.name", login), ("user.email", f"{login}@users.noreply.github.com")]
    env.update({"GH_TOKEN": token, "GITHUB_TOKEN": token, "GIT_CONFIG_COUNT": str(len(config))})
    for i, (key, value) in enumerate(config):
        env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"] = key, value
    return env


class Handler(BaseHTTPRequestHandler):
    server_version = "moloko-codex"
    sys_version = ""

    def log_message(self, format: str, *args: Any) -> None:
        return  # no request logs: bodies are the owner's prompts

    def _json(self, status: int, body: Any) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self) -> bool:
        given = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if TOKEN and hmac.compare_digest(given.encode(), TOKEN.encode()):
            return True
        self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
        return False

    def do_GET(self) -> None:
        if self.path == "/v1/health":
            self._json(HTTPStatus.OK, {"ok": True})
        elif not self._authorized():
            return
        elif self.path == "/v1/status":
            self._json(HTTPStatus.OK, login_status())
        elif self.path == "/v1/models":
            try:
                self._json(HTTPStatus.OK, list_models())
            except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
                self._json(HTTPStatus.BAD_GATEWAY, {"error": str(exc)[:300]})
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_PUT(self) -> None:
        if self.path != "/v1/github":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        if not self._authorized():
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length)) if 0 < length <= 10_000 else {}
            saved = save_github(body.get("token"), body.get("login"))
        except (ValueError, OSError, AttributeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "need token (or null)"})
            return
        self._json(HTTPStatus.OK, {"ok": True, "github": saved})

    def do_POST(self) -> None:
        if self.path != "/v1/run":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        if not self._authorized():
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "body required (at most 2 MB)"})
            return
        try:
            body = json.loads(self.rfile.read(length))
            prompt = str(body["prompt"])
            cwd = inside_workspaces(str(body["cwd"]))
        except (KeyError, ValueError, TypeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "need cwd and prompt"})
            return
        if cwd is None:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "cwd must be a folder of the workspaces"})
            return
        try:
            wait = min(int(body.get("wait_seconds") or QUEUE_WAIT), QUEUE_WAIT)
        except (TypeError, ValueError):
            wait = QUEUE_WAIT
        if not _one_at_a_time.acquire(timeout=wait):
            self._json(HTTPStatus.CONFLICT, {"error": "busy"})
            return
        try:
            self._run(prompt, body.get("model"), body.get("thread_id"), cwd)
        finally:
            _one_at_a_time.release()

    def _run(self, prompt: str, model: Any, thread_id: Any, cwd: Path) -> None:
        cmd = exec_command(
            str(model) if model else None, str(thread_id) if thread_id else None, cwd
        )
        proc = subprocess.Popen(  # noqa: S603 — fixed program, arguments built above
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=run_env(),
            start_new_session=True,  # so a stop ends Codex and everything it started
        )
        stderr: list[str] = []
        reader = threading.Thread(target=lambda: stderr.extend(proc.stderr or []), daemon=True)
        reader.start()
        timer = threading.Timer(TIMEOUT, lambda: _kill(proc))
        timer.start()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write(prompt)
            proc.stdin.close()
            for line in proc.stdout:
                if line.strip():
                    self._chunk(line if line.endswith("\n") else line + "\n")
            code = proc.wait()
            reader.join(timeout=5)
            tail = redact("".join(stderr))[-STDERR_KEEP:]
            self._chunk(json.dumps({"type": "moloko.exit", "code": code, "stderr": tail}) + "\n")
            self._chunk("")
        except (BrokenPipeError, ConnectionResetError):
            _kill(proc)  # the backend stopped the task (or went away)
        finally:
            timer.cancel()
            if proc.poll() is None:
                _kill(proc)

    def _chunk(self, text: str) -> None:
        data = text.encode()
        self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
        self.wfile.flush()


def _kill(proc: subprocess.Popen[str]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)


def main() -> None:
    # Without a token it still starts (healthy), but refuses every request but /v1/health.
    port = int(os.environ.get("CODEX_SERVICE_PORT", "8095"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()  # noqa: S104 — own network


if __name__ == "__main__":
    main()
