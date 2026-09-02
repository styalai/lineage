"""lineage revert — restore workspace to a given experiment."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from .. import reconstruct, storage, workspace
from ..errors import LineageError
from ._ui import bold, fail, info, success, warn


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "revert",
        help="restore workspace to a given experiment.",
        description=(
            "Restore the workspace to the state recorded by a given experiment. "
            "Files that exist in the current workspace but not in the target "
            "experiment are left untouched (lineage never deletes your files)."
        ),
    )
    p.add_argument("exp_id", help="experiment id to revert to")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print the list of files that would change without writing anything",
    )
    p.set_defaults(_func=run)


def run(args, root: Path | None = None) -> int:
    base = Path(root) if root is not None else Path.cwd()
    if not storage.is_initialized(base):
        fail("Not a lineage repository (no .lineage/). Run `lineage add` first.")
    exp_id = args.exp_id
    if not storage.exists(exp_id, base):
        fail(f"Experiment not found: {exp_id}")

    try:
        target_files = reconstruct.reconstruct_files(exp_id, base)
    except LineageError as e:
        fail(str(e))

    current_files = workspace.gather_files(base)

    to_write: list[tuple[Path, bytes]] = []
    to_remove: list[Path] = []
    unchanged = 0
    for rel, data in target_files.items():
        target = base / rel
        if current_files.get(rel) == data:
            unchanged += 1
            continue
        to_write.append((target, data))
    for rel in current_files:
        if rel not in target_files:
            to_remove.append(base / rel)

    if args.dry_run:
        info(f"dry run: revert to {bold(exp_id)}")
        print(f"  would write:  {len(to_write)}")
        print(f"  would remove: {len(to_remove)}  (lineage only writes by default; nothing is removed)")
        print(f"  unchanged:    {unchanged}")
        for p, _ in to_write[:20]:
            print(f"  + {p.relative_to(base)}")
        for p in to_remove[:20]:
            print(f"  - {p.relative_to(base)}")
        if len(to_write) > 20:
            print(f"  ... and {len(to_write) - 20} more")
        return 0

    # Build into a temp dir then swap (atomic on POSIX, best-effort on Windows).
    tmp_root = Path(tempfile.mkdtemp(prefix="lineage-revert-", dir=str(base)))
    try:
        for rel, data in target_files.items():
            target = tmp_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        # Now copy from tmp_root over the workspace, preserving hardlinks elsewhere.
        for rel, data in target_files.items():
            dest = base / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists() or dest.is_symlink():
                try:
                    dest.unlink()
                except IsADirectoryError:
                    shutil.rmtree(dest)
            # Copy from tmp into dest.
            shutil.copy2(tmp_root / rel, dest)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    success(
        f"reverted workspace to {bold(exp_id)} "
        f"({len(to_write)} files updated, {unchanged} unchanged)"
    )
    if to_remove:
        warn(
            f"{len(to_remove)} file(s) in the workspace are not part of {exp_id}; "
            f"left untouched (lineage never deletes files outside .lineage/)"
        )
    return 0
