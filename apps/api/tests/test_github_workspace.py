"""GitHub ↔ workspace: downloading a repository (github_checkout), committing many files in
one commit (github_commit_files), and what a refused write says."""

from __future__ import annotations

import io
import json
import os
import stat
import tarfile
from pathlib import Path
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI

from app.integrations import github as gh
from app.providers import mock_provider
from app.services.users import UserService
from app.workspaces.archive import ArchiveError, unpack_repository
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
from tests.tools_helpers import approvals, audit_actions, scripted, tool_agent, tool_calls

SHA = "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d"
TOP = "me-app-7fd1a60"
Entry = tuple[str, bytes | None, dict[str, Any]]


def tarball(entries: list[Entry], comment: str = SHA) -> bytes:
    """A .tar.gz like GitHub's: entries are (name, data or None for a folder, TarInfo fields)."""
    buf = io.BytesIO()
    with tarfile.open(
        fileobj=buf, mode="w:gz", format=tarfile.PAX_FORMAT, pax_headers={"comment": comment}
    ) as tar:
        for name, data, extra in entries:
            info = tarfile.TarInfo(name)
            info.mode = 0o644
            if data is None and "type" not in extra:
                info.type, info.mode = tarfile.DIRTYPE, 0o755
            for key, value in extra.items():
                setattr(info, key, value)
            if data is not None:
                info.size = len(data)
            tar.addfile(info, io.BytesIO(data) if data is not None else None)
    return buf.getvalue()


REPO_TAR: list[Entry] = [
    (TOP, None, {}),
    (f"{TOP}/package.json", b'{"name": "app"}', {}),
    (f"{TOP}/src", None, {}),
    (f"{TOP}/src/index.ts", b"export const x = 1;\n", {}),
    (f"{TOP}/scripts/run.sh", b"#!/bin/sh\necho hi\n", {"mode": 0o755}),
    (f"{TOP}/link", None, {"type": tarfile.SYMTYPE, "linkname": "/etc/passwd"}),
    (f"{TOP}/hard", None, {"type": tarfile.LNKTYPE, "linkname": f"{TOP}/package.json"}),
    (f"{TOP}/dev", None, {"type": tarfile.CHRTYPE, "devmajor": 1, "devminor": 3}),
]


def write(tmp: Path, data: bytes) -> Path:
    path = tmp / "repo.tar.gz"
    path.write_bytes(data)
    return path


# --- safe unpacking ------------------------------------------------------------------------------


def test_a_repository_is_unpacked_without_links_or_devices(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    out = unpack_repository(
        write(tmp_path, tarball(REPO_TAR)), root, "app", max_files=100, max_bytes=10_000
    )
    assert sorted(out.files) == ["app/package.json", "app/scripts/run.sh", "app/src/index.ts"]
    assert out.commit == SHA and out.skipped == 3
    assert (root / "app/src/index.ts").read_text() == "export const x = 1;\n"
    assert stat.S_IMODE(os.stat(root / "app/scripts/run.sh").st_mode) == 0o755
    assert stat.S_IMODE(os.stat(root / "app/package.json").st_mode) == 0o644
    for name in ("link", "hard", "dev"):
        assert not os.path.lexists(root / "app" / name)


@pytest.mark.parametrize(
    "bad", [f"{TOP}/../../escape.txt", "/etc/cron.d/x", f"{TOP}/a/../../../b", f"{TOP}\\..\\x"]
)
def test_unsafe_paths_refuse_the_whole_archive(tmp_path: Path, bad: str) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    entries: list[Entry] = [(f"{TOP}/ok.txt", b"ok", {}), (bad, b"evil", {})]
    with pytest.raises(ArchiveError, match="unsafe path"):
        unpack_repository(write(tmp_path, tarball(entries)), root, "app", max_files=9, max_bytes=99)
    assert not (root / "app" / "ok.txt").exists()  # checked before anything is written
    assert not (tmp_path / "escape.txt").exists()


def test_limits_are_checked_before_writing(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    many: list[Entry] = [(f"{TOP}/f{i}.txt", b"x", {}) for i in range(5)]
    with pytest.raises(ArchiveError, match="more than 4 files"):
        unpack_repository(write(tmp_path, tarball(many)), root, "app", max_files=4, max_bytes=999)
    big: list[Entry] = [(f"{TOP}/a.bin", b"x" * 600, {}), (f"{TOP}/b.bin", b"y" * 600, {})]
    with pytest.raises(ArchiveError, match="larger than 1000 bytes"):
        unpack_repository(write(tmp_path, tarball(big)), root, "app", max_files=9, max_bytes=1000)
    assert not (root / "app").exists() or not any((root / "app").iterdir())


def test_a_link_in_the_workspace_is_never_followed(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    outside = tmp_path / "outside"
    (root / "app").mkdir(parents=True)
    outside.mkdir()
    (root / "app" / "src").symlink_to(outside)  # e.g. made by a sandbox command
    with pytest.raises(ArchiveError, match="symbolic link"):
        unpack_repository(
            write(tmp_path, tarball(REPO_TAR)), root, "app", max_files=100, max_bytes=10_000
        )
    assert list(outside.iterdir()) == []


# --- the tool ---------------------------------------------------------------------------------


@pytest.fixture
async def tool_app(app_factory: AppFactory, tmp_path: Path) -> FastAPI:
    app = await app_factory(workspace_root=str(tmp_path / "ws"), app_encryption_key="k" * 44)
    async with app.state.db.sessionmaker() as db:
        await UserService(db).create_owner(OWNER_USERNAME, OWNER_PASSWORD, "Owner")
    app.state.queue = RecordingQueue()
    return app


class FakeGitHub:
    """api.github.com + codeload.github.com for the repository me/app."""

    def __init__(self, archive: bytes = b"", *, archive_host: str = "codeload.github.com") -> None:
        self.archive = archive
        self.archive_host = archive_host
        self.log: list[httpx2.Request] = []
        self.refs: dict[str, str] = {"main": "base-commit"}
        self.posted: dict[str, Any] = {}
        self.refuse_writes = False

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.log.append(request)
        path, method = request.url.path, request.method
        if request.url.host == self.archive_host:
            return httpx2.Response(200, content=self.archive)
        if path == "/repos/me/app":
            return httpx2.Response(200, json={"default_branch": "main"})
        if path.startswith("/repos/me/app/tarball/"):
            ref = path.removeprefix("/repos/me/app/tarball/")
            url = f"https://{self.archive_host}/me/app/legacy.tar.gz/refs/heads/{ref}?token=TMP"
            return httpx2.Response(302, headers={"location": url})
        if method != "GET" and self.refuse_writes:
            return httpx2.Response(
                403, json={"message": "Resource not accessible by personal access token"}
            )
        return self.git_data(path, method, request)

    def git_data(self, path: str, method: str, request: httpx2.Request) -> httpx2.Response:
        if path.startswith("/repos/me/app/git/ref/heads/"):
            branch = path.removeprefix("/repos/me/app/git/ref/heads/")
            if branch not in self.refs:
                return httpx2.Response(404, json={"message": "Not Found"})
            return httpx2.Response(200, json={"object": {"sha": self.refs[branch]}})
        if path.startswith("/repos/me/app/git/commits/") and method == "GET":
            return httpx2.Response(200, json={"tree": {"sha": "base-tree"}})
        body = json.loads(request.content or b"{}")
        if path == "/repos/me/app/git/blobs":
            self.posted.setdefault("blobs", []).append(body)
            return httpx2.Response(201, json={"sha": f"blob{len(self.posted['blobs'])}"})
        if path == "/repos/me/app/git/trees":
            self.posted["tree"] = body
            return httpx2.Response(201, json={"sha": "new-tree"})
        if path == "/repos/me/app/git/commits":
            self.posted["commit"] = body
            return httpx2.Response(201, json={"sha": "c0ffee1234567890"})
        if path == "/repos/me/app/git/refs" and method == "POST":
            self.posted["new_ref"] = body
            return httpx2.Response(201, json={})
        if path.startswith("/repos/me/app/git/refs/heads/") and method == "PATCH":
            self.posted["moved_ref"] = (path.removeprefix("/repos/me/app/git/refs/heads/"), body)
            return httpx2.Response(200, json={})
        return httpx2.Response(404, json={"message": "Not Found"})


async def connect_github(client: Any) -> None:
    resp = await client.put(
        "/api/v1/integrations/github",
        json={"token": "github_pat_" + "w" * 40, "allowed_repos": ["me/app"]},
        headers=await csrf_headers(client),
    )
    assert resp.status_code == 200, resp.text


async def run_tools(
    app: FastAPI, steps: list[Any], tools: list[str], autonomy: str = "balanced"
) -> tuple[str, Any]:
    mock_provider._handlers[:] = [scripted(*steps)]  # the `handlers` fixture restores them
    async with logged_in_client(app) as client:
        await connect_github(client)
        agent = await tool_agent(client, autonomy=autonomy, tools=tools)
        task_id = (await run_agent(client, agent["id"], "Work on the repo")).json()["task"]["id"]
        await drain(app, app.state.queue)
    return task_id, agent


@pytest.fixture
def handlers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mock_provider, "_handlers", [])


async def test_checkout_downloads_the_repository_into_the_workspace(
    tool_app: FastAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, handlers: None
) -> None:
    fake = FakeGitHub(tarball(REPO_TAR))
    monkeypatch.setattr(gh, "TRANSPORT", httpx2.MockTransport(fake.handler))
    task_id, _ = await run_tools(
        tool_app,
        [
            ("github_checkout", {"repo": "me/app"}),
            ("github_checkout", {"repo": "me/app"}),  # again: the folder is not empty now
            "done",
        ],
        ["github_checkout"],
    )
    first, again = await tool_calls(tool_app, task_id)
    assert (first.category, first.status) == ("write", "succeeded"), first.result
    assert "Downloaded me/app (main, commit 7fd1a60b01) into app/: 3 files" in (first.result or "")
    assert "Skipped 3" in (first.result or "")
    assert again.status == "failed" and "not empty" in (again.result or "")
    [ws] = [p for p in (tmp_path / "ws").iterdir() if not p.name.startswith(".")]
    assert (ws / "app/src/index.ts").read_text() == "export const x = 1;\n"
    assert not any(p.name.startswith(".gh-") for p in (tmp_path / "ws").iterdir())  # cleaned
    codeload = [r for r in fake.log if r.url.host == "codeload.github.com"]
    assert codeload and "authorization" not in codeload[0].headers  # our token stays home
    changed = await audit_actions(tool_app, "workspace.files_changed")
    assert sorted(changed[0].details["changed"]) == [
        "app/package.json",
        "app/scripts/run.sh",
        "app/src/index.ts",
    ]
    assert all("TMP" not in json.dumps(a.details) for a in await audit_actions(tool_app, ""))


async def test_replacing_files_of_an_existing_folder_needs_approval(
    tool_app: FastAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, handlers: None
) -> None:
    fake = FakeGitHub(tarball(REPO_TAR))
    monkeypatch.setattr(gh, "TRANSPORT", httpx2.MockTransport(fake.handler))
    task_id, _ = await run_tools(
        tool_app,
        [
            ("github_checkout", {"repo": "me/app", "folder": "code"}),
            ("github_checkout", {"repo": "me/app", "folder": "code", "overwrite": True}),
            "done",
        ],
        ["github_checkout"],
    )
    first, second = await tool_calls(tool_app, task_id)
    assert first.status == "succeeded"
    assert (second.category, second.status) == ("sensitive", "awaiting_approval")
    [pending] = await approvals(tool_app, task_id)
    assert "workspace:code/" in pending.resources and "replaced" in pending.consequences


@pytest.mark.parametrize("folder", [".", "", "../other", "/abs"])
async def test_checkout_stays_inside_the_workspace(
    tool_app: FastAPI, monkeypatch: pytest.MonkeyPatch, handlers: None, folder: str
) -> None:
    fake = FakeGitHub(tarball(REPO_TAR))
    monkeypatch.setattr(gh, "TRANSPORT", httpx2.MockTransport(fake.handler))
    args: dict[str, Any] = {"repo": "me/app", "folder": folder}
    task_id, _ = await run_tools(tool_app, [("github_checkout", args), "done"], ["github_checkout"])
    if folder == "":  # empty = the default folder (the repository name)
        assert (await tool_calls(tool_app, task_id))[0].status == "succeeded"
        return
    call = (await tool_calls(tool_app, task_id))[0]
    assert call.status == "denied" and "scope" in (call.decision_reason or "")
    assert not [r for r in fake.log if "tarball" in r.url.path]


async def test_archives_only_come_from_codeload(
    tool_app: FastAPI, monkeypatch: pytest.MonkeyPatch, handlers: None
) -> None:
    elsewhere = FakeGitHub(tarball(REPO_TAR), archive_host="evil.example")
    monkeypatch.setattr(gh, "TRANSPORT", httpx2.MockTransport(elsewhere.handler))
    task_id, _ = await run_tools(
        tool_app, [("github_checkout", {"repo": "me/app"}), "done"], ["github_checkout"]
    )
    call = (await tool_calls(tool_app, task_id))[0]
    assert call.status == "failed" and "did not offer" in (call.result or "")
    assert not [r for r in elsewhere.log if r.url.host == "evil.example"]


async def test_archives_stop_at_the_size_limit(
    tool_app: FastAPI, monkeypatch: pytest.MonkeyPatch, handlers: None
) -> None:
    monkeypatch.setattr(tool_app.state.settings, "github_checkout_max_bytes", 1_000_000)
    huge = FakeGitHub(os.urandom(1_200_000))
    monkeypatch.setattr(gh, "TRANSPORT", httpx2.MockTransport(huge.handler))
    task_id, _ = await run_tools(
        tool_app,
        [("github_checkout", {"repo": "me/app", "folder": "x"}), "done"],
        ["github_checkout"],
    )
    call = (await tool_calls(tool_app, task_id))[0]
    assert call.status == "failed" and "larger than 1000000 bytes" in (call.result or "")
