"""Safe paths inside a workspace directory.

Every tool path is relative to the workspace root. We refuse absolute paths, ``..``
segments, NUL bytes, and symlinks anywhere on the path (a symlink could point outside
the workspace — the sandbox can create them). Checks use ``lstat`` on each component,
so a link is never followed.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path, PurePosixPath

from app.tools.base import ScopeError

MAX_PATH = 512


def normalise(rel: str) -> PurePosixPath:
    """Validate a workspace-relative path without touching the disk."""
    if not isinstance(rel, str) or "\x00" in rel or len(rel) > MAX_PATH:
        raise ScopeError("invalid path")
    rel = rel.strip().replace("\\", "/")
    if rel in ("", ".", "./"):
        return PurePosixPath(".")
    path = PurePosixPath(rel)
    if path.is_absolute():
        raise ScopeError("paths must be relative to the workspace")
    parts = [p for p in path.parts if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ScopeError("paths may not contain '..'")
    return PurePosixPath(*parts) if parts else PurePosixPath(".")


def resolve(root: Path, rel: str, *, must_exist: bool = False) -> Path:
    """The absolute path for ``rel`` under ``root``; no component may be a symlink."""
    clean = normalise(rel)
    current = root
    if root.is_symlink():
        raise ScopeError("the workspace root is a symlink")
    for part in clean.parts if str(clean) != "." else ():
        current = current / part
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            if must_exist:
                raise ScopeError(f"'{clean}' does not exist") from None
            continue  # the rest does not exist yet: nothing to follow
        if stat.S_ISLNK(st.st_mode):
            raise ScopeError(f"'{clean}' goes through a symbolic link")
    return current


def relative(root: Path, path: Path) -> str:
    return str(PurePosixPath(path.relative_to(root)))
