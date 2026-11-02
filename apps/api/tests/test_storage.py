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


# --- Off-site copies (infrastructure/backup/offsite.sh writes these files) -------------------


def _write(root: Path, name: str, text: str) -> None:
    (root / name).write_text(text + "\n")


def _iso(hours_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


REPO = "s3:https://s3.eu-central-003.backblazeb2.com/moloko-backups/moloko"


def _healthy_offsite(root: Path, *, copy_hours_ago: float = 2) -> None:
    """The files exactly as offsite.sh writes them after a good night."""
    _write(
        root,
        "offsite-config.json",
        f'{{"enabled": true, "at": "{_iso(30)}", "kind": "s3", "repository": "{REPO}", '
        '"keep_daily": 7, "keep_weekly": 4, "keep_monthly": 6, "check_days": 7, '
        '"drill_days": 7, "check_subset": "10%"}',
    )
    _write(
        root,
        "offsite-status.json",
        f'{{"ok": true, "at": "{_iso(copy_hours_ago)}", "repository": "{REPO}"}}',
    )
    _write(
        root,
        "offsite-last.json",
        f'{{"at": "{_iso(copy_hours_ago)}", "repository": "{REPO}", "snapshot": "2466100c", '
        '"source": "moloko-20261102-030000.dump", "source_at": "2026-11-02T03:00:12Z", '
        '"bytes": 11470, "added_bytes": 4079, "stored_bytes": 15633, "snapshots": 9}',
    )
    _write(
        root,
        "offsite-check.json",
        f'{{"ok": true, "at": "{_iso(50)}", "subset": "10%", "detail": "no errors were found"}}',
    )
    _write(
        root,
        "offsite-drill.json",
        f'{{"ok": true, "at": "{_iso(50)}", "dump": "moloko-20261102-030000.dump", '
        '"snapshot": "2466100c", "same_as_local": true, "detail": "restored: users=1 agents=3"}',
    )


def _local_ok(root: Path) -> None:
    root.mkdir(exist_ok=True)
    _write(root, "status.json", json.dumps({"ok": True, "at": _iso(2)}))


def test_offsite_off_is_warned(tmp_path: Path) -> None:
    root = tmp_path / "b"
    _local_ok(root)
    _write(root, "offsite-config.json", '{"enabled": false, "at": "2026-11-02T03:00:00Z"}')
    status = storage_status(make_settings(backup_dir=str(root), workspace_root=str(tmp_path)))
    offsite = status["backups"]["offsite"]
    assert offsite["enabled"] is False and offsite["last_copy"] is None
    assert {"offsite_off", "same_disk"} <= set(status["warnings"])


def test_offsite_unknown_before_the_new_backup_image(tmp_path: Path) -> None:
    root = tmp_path / "b"
    _local_ok(root)  # an old backup container never writes offsite-config.json
    status = storage_status(make_settings(backup_dir=str(root), workspace_root=str(tmp_path)))
    assert status["backups"]["offsite"]["enabled"] is False
    assert "offsite_off" in status["warnings"]


def test_offsite_healthy(tmp_path: Path) -> None:
    root = tmp_path / "b"
    _local_ok(root)
    _healthy_offsite(root)
    status = storage_status(make_settings(backup_dir=str(root), workspace_root=str(tmp_path)))
    offsite = status["backups"]["offsite"]
    assert offsite["enabled"] and offsite["kind"] == "s3" and offsite["repository"] == REPO
    assert (offsite["keep_daily"], offsite["keep_weekly"], offsite["keep_monthly"]) == (7, 4, 6)
    copy = offsite["last_copy"]
    assert copy["snapshot"] == "2466100c" and copy["stored_bytes"] == 15633
    assert copy["snapshots"] == 9 and copy["source"] == "moloko-20261102-030000.dump"
    assert 1.9 <= offsite["age_hours"] <= 2.1
    assert offsite["check"]["ok"] and offsite["check"]["subset"] == "10%"
    assert offsite["drill"]["ok"] and offsite["drill"]["same_as_local"] is True
    # A recent off-site copy protects the data: local copies on the same disk are fine then.
    assert status["backups"]["same_disk_as_data"] is True
    assert not [w for w in status["warnings"] if w.startswith("offsite") or w == "same_disk"]


def test_offsite_failures_are_warned_and_the_last_good_copy_kept(tmp_path: Path) -> None:
    root = tmp_path / "b"
    _local_ok(root)
    _healthy_offsite(root, copy_hours_ago=60)
    _write(
        root,
        "offsite-status.json",
        f'{{"ok": false, "at": "{_iso(1)}", "repository": "/mnt/moloko-offsite", '
        '"error_code": "wrong_password", "error": "Fatal: wrong password or no key found"}',
    )
    _write(
        root,
        "offsite-check.json",
        f'{{"ok": false, "at": "{_iso(1)}", "subset": "10%", "error_code": "failed", '
        '"detail": "Fatal: repository contains errors"}',
    )
    _write(
        root,
        "offsite-drill.json",
        f'{{"ok": false, "at": "{_iso(1)}", "snapshot": "2466100c", "error_code": "corrupt", '
        '"detail": "the workspace archive in the copy is damaged"}',
    )
    status = storage_status(make_settings(backup_dir=str(root), workspace_root=str(tmp_path)))
    offsite = status["backups"]["offsite"]
    assert offsite["last_attempt"]["error_code"] == "wrong_password"
    assert offsite["last_copy"]["snapshot"] == "2466100c"
    assert offsite["drill"]["error_code"] == "corrupt"
    assert {
        "offsite_failed",
        "offsite_too_old",
        "offsite_check_failed",
        "offsite_drill_failed",
        "same_disk",  # no recent off-site copy: the same-disk warning is back
    } <= set(status["warnings"])


def test_offsite_no_copy_yet_and_broken_files(tmp_path: Path) -> None:
    root = tmp_path / "b"
    _local_ok(root)
    _write(root, "offsite-config.json", '{"enabled": true, "kind": "disk", "keep_daily": "7"}')
    _write(root, "offsite-last.json", '{"at": "yesterday", "snapshot": 5}')  # malformed
    _write(root, "offsite-check.json", "not json")
    status = storage_status(make_settings(backup_dir=str(root), workspace_root=str(tmp_path)))
    offsite = status["backups"]["offsite"]
    assert offsite["enabled"] and offsite["keep_daily"] is None
    assert offsite["last_copy"] is None and offsite["check"] is None
    assert "offsite_no_copy_yet" in status["warnings"]


async def test_storage_api_reports_offsite(app_factory: AppFactory, tmp_path: Path) -> None:
    root = tmp_path / "b"
    _local_ok(root)
    _healthy_offsite(root)
    app: FastAPI = await app_factory(backup_dir=str(root), workspace_root=str(tmp_path))
    async with app.state.db.sessionmaker() as db:
        await UserService(db).create_owner(OWNER_USERNAME, OWNER_PASSWORD, "Owner")
    async with logged_in_client(app) as client:
        body = (await client.get("/api/v1/system/storage")).json()
    offsite = body["backups"]["offsite"]
    assert offsite["enabled"] and offsite["last_copy"]["snapshot"] == "2466100c"
    assert offsite["drill"]["same_as_local"] is True
    assert not [w for w in body["warnings"] if w.startswith("offsite")]
