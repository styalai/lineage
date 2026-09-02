"""Reconstruct an experiment's file map by walking back to the nearest snapshot."""

from __future__ import annotations

import shutil
from pathlib import Path

from . import diff, snapshot, storage
from .diff import FileState
from .errors import LineageError


def reconstruct_files(exp_id: str, root: Path | None = None) -> dict[str, bytes]:
    """Return the full file map for ``exp_id`` by replaying diffs onto a snapshot.

    Raises ``LineageError`` if reconstruction fails (e.g. a diff is missing).
    """
    chain = storage.chain_to_snapshot(exp_id, root)
    snap_id = chain[0]
    rest = chain[1:]
    if not exists_snapshot(snap_id, root):
        raise LineageError(f"Snapshot missing for experiment {snap_id!r}")
    snap_root = storage.snapshot_dir(snap_id, root)
    state = FileState(files=snapshot.list_snapshot_files(snap_root))
    for cid in rest:
        patch_path = storage.diff_path(cid, root)
        if not patch_path.is_file():
            raise LineageError(f"Diff missing for {cid!r}: {patch_path}")
        text = patch_path.read_text(encoding="utf-8")
        diff.apply_patch_text(state, text, reverse=False)
    return state.files


def exists_snapshot(exp_id: str, root: Path | None = None) -> bool:
    return storage.snapshot_dir(exp_id, root).is_dir()


def write_reconstructed(exp_id: str, dest_root: Path, root: Path | None = None) -> int:
    """Reconstruct ``exp_id`` into ``dest_root``. Returns number of files written.

    Files in ``dest_root`` that are NOT in the reconstruction are left untouched.
    """
    files = reconstruct_files(exp_id, root)
    dest_root.mkdir(parents=True, exist_ok=True)
    count = 0
    for rel, data in files.items():
        target = dest_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        count += 1
    return count


def diff_experiments(
    a: str, b: str, root: Path | None = None
) -> dict[str, tuple[bytes | None, bytes | None]]:
    """Return ``{rel_path: (a_bytes, b_bytes)}`` for every file in either experiment.

    Either side may be missing (None) for files that don't exist in that experiment.
    """
    fa = reconstruct_files(a, root)
    fb = reconstruct_files(b, root)
    paths = sorted(set(fa) | set(fb))
    return {p: (fa.get(p), fb.get(p)) for p in paths}
