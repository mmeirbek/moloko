"""The sandbox container spec (no Docker needed)."""

from __future__ import annotations

import uuid

from app.sandbox.runner import RunnerSettings, container_spec


def test_the_task_folder_is_mounted_without_copy_up() -> None:
    """Without NoCopy, Docker copies the image's root-owned /workspace onto an empty task
    folder and hands it to root: the agent then cannot write its own files."""
    wid = uuid.uuid4()
    spec = container_spec(RunnerSettings(sandbox_workspaces_volume="ws"), wid, ["true"])
    mount = spec["HostConfig"]["Mounts"][0]
    assert mount["Type"] == "volume" and mount["Target"] == "/workspace"
    assert mount["VolumeOptions"] == {"Subpath": str(wid), "NoCopy": True}
    assert spec["User"] == "10001:10001" and spec["WorkingDir"] == "/workspace"
