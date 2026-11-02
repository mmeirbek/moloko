"""Backups and disk space as the owner sees them (spec 21.2, 21.3).

The backup container writes small JSON status files into BACKUP_DIR (mounted read-only
here): status.json / last-drill.json for the local backups, offsite-*.json for the
encrypted off-site copies (infrastructure/backup/offsite.sh). They never hold secrets.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.schemas.tasks import OffsiteAttempt, OffsiteCheck, OffsiteCopy, OffsiteDrill, OffsiteStatus


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _disk(path: Path, warn_percent: float) -> dict[str, Any] | None:
    try:
        st = os.statvfs(path)
    except OSError:
        return None
    total, free = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
    percent = round(100 * free / total, 1) if total else 0.0
    return {
        "path": str(path),
        "total_bytes": total,
        "free_bytes": free,
        "free_percent": percent,
        "low": percent < warn_percent,
    }


def _age_hours(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        at = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((datetime.now(UTC) - at).total_seconds() / 3600, 1)


def _files(root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for kind in ("daily", "weekly"):
        folder = root / kind
        if not folder.is_dir():
            continue
        for item in sorted(folder.iterdir(), reverse=True):
            if item.suffix in (".dump", ".gz") and item.is_file():
                st = item.stat()
                out.append(
                    {
                        "name": item.name,
                        "kind": kind,
                        "bytes": st.st_size,
                        "at": datetime.fromtimestamp(st.st_mtime, UTC).isoformat(),
                    }
                )
    return out[:40]


def _parsed[M: BaseModel](model: type[M], data: dict[str, Any] | None) -> M | None:
    """A status file written by the backup container, or None when missing or malformed."""
    if data is None:
        return None
    try:
        return model.model_validate(data)
    except ValidationError:
        return None


def _offsite(backups: Path, settings: Settings) -> tuple[dict[str, Any], list[str], bool]:
    """Off-site copies (infrastructure/backup/offsite.sh): status, warnings, protected?"""
    config = _read_json(backups / "offsite-config.json") or {}
    enabled = config.get("enabled") is True
    attempt = _parsed(OffsiteAttempt, _read_json(backups / "offsite-status.json"))
    copy = _parsed(OffsiteCopy, _read_json(backups / "offsite-last.json"))
    check = _parsed(OffsiteCheck, _read_json(backups / "offsite-check.json"))
    drill = _parsed(OffsiteDrill, _read_json(backups / "offsite-drill.json"))
    age = None
    if copy is not None:
        at = copy.at if copy.at.tzinfo else copy.at.replace(tzinfo=UTC)
        age = round((datetime.now(UTC) - at).total_seconds() / 3600, 1)

    def text(key: str) -> str | None:
        value = config.get(key)
        return value[:300] if isinstance(value, str) else None

    def number(key: str) -> int | None:
        value = config.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    status = OffsiteStatus(
        enabled=enabled,
        kind=text("kind") if enabled else None,
        repository=text("repository") if enabled else None,
        keep_daily=number("keep_daily"),
        keep_weekly=number("keep_weekly"),
        keep_monthly=number("keep_monthly"),
        check_days=number("check_days"),
        drill_days=number("drill_days"),
        last_attempt=attempt if enabled else None,
        last_copy=copy if enabled else None,
        age_hours=age if enabled else None,
        check=check if enabled else None,
        drill=drill if enabled else None,
    )
    warnings: list[str] = []
    if not enabled:
        return status.model_dump(), ["offsite_off"], False
    failed = attempt is not None and not attempt.ok
    if failed:
        warnings.append("offsite_failed")
    elif copy is None:
        warnings.append("offsite_no_copy_yet")
    too_old = age is not None and age > settings.offsite_max_age_hours
    if too_old:
        warnings.append("offsite_too_old")
    if check is not None and not check.ok:
        warnings.append("offsite_check_failed")
    if drill is not None and not drill.ok:
        warnings.append("offsite_drill_failed")
    protected = copy is not None and not failed and not too_old
    return status.model_dump(), warnings, protected


def storage_status(settings: Settings) -> dict[str, Any]:
    backups = Path(settings.backup_dir)
    data = Path(settings.workspace_root)
    present = backups.is_dir()
    last = _read_json(backups / "status.json") if present else None
    drill = _read_json(backups / "last-drill.json") if present else None
    age = _age_hours(last.get("at") if last else None)
    same_disk = None
    if present and data.exists():
        try:
            same_disk = os.stat(backups).st_dev == os.stat(data).st_dev
        except OSError:
            same_disk = None
    warnings: list[str] = []
    if not present:
        warnings.append("not_configured")
    elif last is None:
        warnings.append("no_backup_yet")
    else:
        if not last.get("ok"):
            warnings.append("last_backup_failed")
        if age is not None and age > settings.backup_max_age_hours:
            warnings.append("backup_too_old")
    if drill is not None and not drill.get("ok"):
        warnings.append("restore_drill_failed")
    if present:
        offsite, offsite_warnings, protected = _offsite(backups, settings)
        warnings.extend(offsite_warnings)
    else:
        offsite, protected = OffsiteStatus(enabled=False).model_dump(), False
    # Local copies on the data disk are fine as a fast first resort while a recent
    # off-site copy exists; without one they are no protection.
    if same_disk and not protected:
        warnings.append("same_disk")
    disks = [
        d
        for d in (
            _disk(data, settings.disk_warn_free_percent),
            _disk(backups, settings.disk_warn_free_percent) if present else None,
        )
        if d
    ]
    if any(d["low"] for d in disks):
        warnings.append("low_disk")
    return {
        "backups": {
            "configured": present,
            "last": last,
            "age_hours": age,
            "drill": drill,
            "files": _files(backups) if present else [],
            "same_disk_as_data": same_disk,
            "offsite": offsite,
        },
        "disks": disks,
        "warnings": warnings,
    }
