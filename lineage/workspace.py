"""Gather the current workspace files into an in-memory map.

Excludes ``.lineage/``, ``.git/``, and a small set of common noise patterns.
This module is intentionally NOT aware of ``.gitignore`` — see README for rationale.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

# Directories we always skip (top-level or nested).
EXCLUDED_DIRS: frozenset[str] = frozenset(
    {
        ".lineage",
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
    }
)

# File basenames we always skip.
EXCLUDED_FILES: frozenset[str] = frozenset(
    {
        ".DS_Store",
        "Thumbs.db",
    }
)

# Suffix patterns we always skip.
EXCLUDED_SUFFIXES: tuple[str, ...] = (
    ".pyc",
    ".pyo",
)


def is_excluded_dir(name: str) -> bool:
    return name in EXCLUDED_DIRS


def is_excluded_file(name: str) -> bool:
    if name in EXCLUDED_FILES:
        return True
    return any(name.endswith(suf) for suf in EXCLUDED_SUFFIXES)


def gather_files(root: Path | None = None) -> dict[str, bytes]:
    """Walk ``root`` (default: CWD) and return ``{rel_posix_path: bytes}``.

    Keys use forward slashes and are relative to ``root``. Symlinks are not
    followed to avoid cycles.
    """
    base = Path(root) if root is not None else Path.cwd()
    base = base.resolve()
    files: dict[str, bytes] = {}

    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        # Filter dirs in-place so os.walk doesn't descend into them.
        dirnames[:] = [d for d in dirnames if not is_excluded_dir(d)]
        for fname in filenames:
            if is_excluded_file(fname):
                continue
            full = Path(dirpath) / fname
            try:
                rel = full.relative_to(base)
            except ValueError:
                continue
            rel_posix = rel.as_posix()
            try:
                data = full.read_bytes()
            except OSError:
                # Skip unreadable files rather than fail the whole operation.
                continue
            files[rel_posix] = data
    return files


def walk_files(root: Path | None = None) -> Iterator[tuple[Path, str]]:
    """Yield ``(absolute_path, rel_posix)`` for every file under ``root``."""
    base = Path(root) if root is not None else Path.cwd()
    base = base.resolve()
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames[:] = [d for d in dirnames if not is_excluded_dir(d)]
        for fname in filenames:
            if is_excluded_file(fname):
                continue
            full = Path(dirpath) / fname
            try:
                rel = full.relative_to(base)
            except ValueError:
                continue
            yield full, rel.as_posix()
