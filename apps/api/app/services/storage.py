"""Backups and disk space as the owner sees them (spec 21.2, 21.3)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import Settings


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
    if same_disk:
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
        },
        "disks": disks,
        "warnings": warnings,
    }
