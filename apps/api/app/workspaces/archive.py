"""Unpacking a repository archive (a GitHub .tar.gz) into a workspace folder — safely.

Two passes. The first reads only the entry headers and refuses the whole archive if any
entry has an absolute path, ``..`` or a NUL byte, or if the files exceed the count or size
limit (counted from the headers before any data is read, so a "zip bomb" stops early). It
also refuses if something on a target path is in the way (a link, a folder where a file
goes). Symbolic links, hard links, devices and FIFOs are never unpacked; they are only
counted. The second pass writes regular files with ``O_NOFOLLOW`` under paths checked with
``app.workspaces.paths.resolve`` (no symlink anywhere on the path), mode 0644 or 0755.
GitHub puts everything under one top folder (``owner-repo-sha/``); it is stripped.
"""

from __future__ import annotations

import os
import shutil
import tarfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from app.tools.base import ScopeError
from app.workspaces.paths import relative, resolve


class ArchiveError(Exception):
    """The archive cannot be unpacked safely (message safe to show)."""


@dataclass
class Unpacked:
    files: list[str] = field(default_factory=list)  # relative to the workspace root
    total_bytes: int = 0
    skipped: int = 0  # links and other special entries, not unpacked
    commit: str | None = None  # GitHub writes the commit id into the archive's comment


def _inside(name: str) -> str | None:
    """The entry's path below GitHub's top folder; None for the top folder itself."""
    if "\x00" in name or name.startswith("/") or "\\" in name:
        raise ArchiveError("The archive contains an unsafe path.")
    parts = [p for p in PurePosixPath(name).parts if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ArchiveError("The archive contains an unsafe path.")
    return "/".join(parts[1:]) or None


def unpack_repository(
    archive: Path, root: Path, folder: str, *, max_files: int, max_bytes: int
) -> Unpacked:
    """Unpack ``archive`` into ``root/folder`` (``folder`` is workspace-relative)."""
    out = Unpacked()
    try:
        tar = tarfile.open(archive, "r:gz")  # noqa: SIM115 — closed by the with below
    except (tarfile.TarError, OSError):
        raise ArchiveError("The repository archive is damaged.") from None
    with tar:
        comment = tar.pax_headers.get("comment")
        out.commit = comment if comment and len(comment) <= 64 else None
        planned: list[tuple[tarfile.TarInfo, Path]] = []
        dirs: list[Path] = []
        entries = declared = 0
        try:
            for member in tar:
                entries += 1
                declared += max(member.size, 0)  # what reading on would decompress
                if entries > 2 * max_files + 1000:
                    raise ArchiveError(f"The repository has more than {max_files} files.")
                if declared > max_bytes:
                    raise ArchiveError(
                        f"The repository's files are larger than {max_bytes} bytes "
                        "(GITHUB_CHECKOUT_MAX_BYTES)."
                    )
                rel = _inside(member.name)
                if rel is None:
                    continue
                if member.isdir():
                    dirs.append(_target(root, folder, rel, want_dir=True))
                    continue
                if not member.isreg():  # symlink, hard link, device, fifo
                    out.skipped += 1
                    continue
                if len(planned) >= max_files:
                    raise ArchiveError(
                        f"The repository has more than {max_files} files "
                        "(GITHUB_CHECKOUT_MAX_FILES)."
                    )
                out.total_bytes += member.size
                planned.append((member, _target(root, folder, rel, want_dir=False)))
        except tarfile.TarError:
            raise ArchiveError("The repository archive is damaged.") from None
        current = root / folder
        try:
            for current in dirs:
                current.mkdir(parents=True, exist_ok=True)
            for member, current in planned:
                _write(tar, member, root, current)
                out.files.append(relative(root, current))
        except (OSError, tarfile.TarError) as exc:
            reason = getattr(exc, "strerror", None) or "write error"
            raise ArchiveError(f"Cannot write {relative(root, current)}: {reason}.") from None
    return out


def _target(root: Path, folder: str, rel: str, *, want_dir: bool) -> Path:
    try:
        path = resolve(root, f"{folder}/{rel}")
    except ScopeError as exc:  # a symbolic link on the way, a too long path…
        raise ArchiveError(f"Cannot unpack {rel}: {exc}.") from None
    if path.exists() and path.is_dir() != want_dir:
        raise ArchiveError(f"Cannot unpack {rel}: something else is in the way in the folder.")
    return path


def _write(tar: tarfile.TarFile, member: tarfile.TarInfo, root: Path, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        resolve(root, relative(root, path))  # re-check: no link appeared on the way
    except ScopeError as exc:
        raise ArchiveError(f"Cannot unpack {relative(root, path)}: {exc}.") from None
    source = tar.extractfile(member)
    if source is None:
        raise ArchiveError(f"Cannot read {member.name} from the archive.")
    mode = 0o755 if member.mode & 0o111 else 0o644
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    os.fchmod(fd, mode)  # an existing file would keep its old mode
    with source, os.fdopen(fd, "wb") as fh:
        shutil.copyfileobj(source, fh, 1 << 20)
