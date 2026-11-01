"""Backup status and disk warnings shown in Settings (spec 21.2, 21.3)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI

from app.services.storage import storage_status
from app.services.users import UserService
from tests.conftest import (
    OWNER_PASSWORD,
    OWNER_USERNAME,
    AppFactory,
    logged_in_client,
    make_settings,
)


def test_not_configured_and_first_run(tmp_path: Path) -> None:
    settings = make_settings(
        backup_dir=str(tmp_path / "missing"), workspace_root=str(tmp_path), disk_warn_free_percent=0
    )
    assert storage_status(settings)["warnings"] == ["not_configured"]
    (tmp_path / "b").mkdir()
    settings = make_settings(backup_dir=str(tmp_path / "b"), workspace_root=str(tmp_path))
    status = storage_status(settings)
    assert "no_backup_yet" in status["warnings"]
    assert status["backups"]["same_disk_as_data"] is True and "same_disk" in status["warnings"]


def test_old_failed_backup_and_failed_drill_are_warned(tmp_path: Path) -> None:
    root = tmp_path / "b"
    (root / "daily").mkdir(parents=True)
    (root / "daily" / "moloko-20261101-030000.dump").write_bytes(b"x" * 10)
    old = (datetime.now(UTC) - timedelta(hours=50)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (root / "status.json").write_text(json.dumps({"ok": True, "at": old}))
    (root / "last-drill.json").write_text(json.dumps({"ok": False, "detail": "pg_restore failed"}))
    status = storage_status(make_settings(backup_dir=str(root), workspace_root=str(tmp_path)))
    assert {"backup_too_old", "restore_drill_failed"} <= set(status["warnings"])
    assert status["backups"]["files"][0]["name"] == "moloko-20261101-030000.dump"
    assert status["backups"]["age_hours"] >= 49
    assert status["disks"] and status["disks"][0]["total_bytes"] > 0


async def test_storage_api(app_factory: AppFactory, tmp_path: Path) -> None:
    root = tmp_path / "b"
    root.mkdir()
    (root / "status.json").write_text(json.dumps({"ok": True, "at": datetime.now(UTC).isoformat()}))
    app: FastAPI = await app_factory(backup_dir=str(root), workspace_root=str(tmp_path))
    async with app.state.db.sessionmaker() as db:
        await UserService(db).create_owner(OWNER_USERNAME, OWNER_PASSWORD, "Owner")
    async with logged_in_client(app) as client:
        body = (await client.get("/api/v1/system/storage")).json()
    assert body["backups"]["configured"] and body["backups"]["last"]["ok"]
    assert "backup_too_old" not in body["warnings"]
