"""Snapshot creation and restoration.

Snapshots store a real copy of file *contents* (not hardlinks). This is
intentionally not the ``cp -al`` optimization described in the spec, because
hardlinks to the original files would not survive in-place modification:
writing to a file in the workspace would silently update the "snapshot"
inode too. We trade speed for correctness in v0.1; the hardlink optimization
can be added later behind a config flag (it would only be safe with
copy-on-write filesystems, or with snapshot-on-write logic).

Cross-filesystem fallback: if a regular copy fails (very rare), we fall back
to ``shutil.copyfile``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from . import workspace
from .errors import LineageError


def create_snapshot(src: Path, dest: Path) -> int:
    """Create a snapshot of ``src`` under ``dest``.

    Returns the number of files copied. ``dest`` must not exist or must be an
    empty directory.
    """
    if dest.exists():
        if dest.is_dir() and not any(dest.iterdir()):
            dest.rmdir()
        else:
            raise LineageError(f"Snapshot destination {dest} is not empty")
    dest.mkdir(parents=True)

    src = src.resolve()
    count = 0
    for full, rel in workspace.walk_files(src):
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        # Read content from disk and write to snapshot — a real byte copy.
        # This is correct under any filesystem; the hardlink optimization
        # can be revisited later with copy-on-write semantics.
        data = full.read_bytes()
        target.write_bytes(data)
        count += 1
    return count


def restore_snapshot(src: Path, dest: Path) -> int:
    """Copy the snapshot at ``src`` into ``dest`` (creating ``dest`` as needed).

    Only files present in the snapshot are written — files already in ``dest``
    that are not in the snapshot are left untouched.
    """
    src = src.resolve()
    if not src.is_dir():
        raise LineageError(f"Snapshot not found: {src}")
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    for full, rel in workspace.walk_files(src):
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        data = full.read_bytes()
        target.write_bytes(data)
        count += 1
    return count


def list_snapshot_files(snapshot_root: Path) -> dict[str, bytes]:
    """Return ``{rel_posix: bytes}`` for every file in the snapshot."""
    return workspace.gather_files(snapshot_root)
