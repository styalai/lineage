"""lineage add — create an experiment from the current workspace."""

from __future__ import annotations

from pathlib import Path

from .. import diff as diffmod
from .. import ids, reconstruct, snapshot, storage, workspace
from ..errors import LineageError
from ._ui import bold, fail, info, success


def run(args, root: Path | None = None) -> int:
    base = Path(root) if root is not None else Path.cwd()
    storage.ensure_initialized(base)

    existing = storage.list_ids(base)
    if not existing:
        new_id = ids.ROOT
    else:
        parent_id = _resolve_parent(args, base)
        new_id = ids.next_child_id(parent_id, storage.children_of(parent_id, base))

    storage.create_experiment_dir(new_id, base)

    current_files = workspace.gather_files(base)

    if new_id == ids.ROOT:
        parent_id = ids.ROOT
        parent_files: dict[str, bytes] = {}
    else:
        if parent_id == ids.ROOT and not storage.exists(parent_id, base):
            parent_files = {}
        else:
            parent_files = reconstruct.reconstruct_files(parent_id, base)

    exp_type, patch_text = _decide_and_build(
        new_id=new_id,
        parent_id=parent_id,
        parent_files=parent_files,
        current_files=current_files,
        base=base,
    )

    meta = storage.Meta(
        id=new_id,
        parent=parent_id,
        type=exp_type,
        message=args.message or "",
        created_at=storage.now_iso(),
    )
    storage.save(meta, base)

    # Empty notes file, ready for `lineage note`.
    storage.write_notes(new_id, f"# Notes for {new_id}\n\n", base)

    if exp_type == "snapshot":
        snapshot.create_snapshot(base, storage.snapshot_dir(new_id, base))
    else:
        if patch_text:
            storage.write_text_atomic(storage.diff_path(new_id, base), patch_text)
        else:
            # Empty diff: still create an empty file so the format is uniform.
            storage.write_text_atomic(storage.diff_path(new_id, base), "")

    if new_id == ids.ROOT:
        success(f"created snapshot {bold(new_id)} (root)")
    elif exp_type == "snapshot":
        success(f"created snapshot {bold(new_id)} (parent {parent_id})")
    else:
        success(f"created diff {bold(new_id)} (parent {parent_id})")
    return 0


def _resolve_parent(args, base: Path) -> str:
    explicit = getattr(args, "from_", None) or getattr(args, "from_id", None)
    if explicit:
        if not storage.exists(explicit, base):
            raise LineageError(f"--from: experiment not found: {explicit}")
        return explicit
    latest = storage.find_latest(base)
    if latest is None:
        return ids.ROOT
    return latest


def _decide_and_build(
    *,
    new_id: str,
    parent_id: str,
    parent_files: dict[str, bytes],
    current_files: dict[str, bytes],
    base: Path,
) -> tuple[str, str]:
    """Decide snapshot vs diff and build the diff text if needed.

    Returns ``(type, patch_text)`` where ``patch_text`` is empty for snapshots.
    """
    # The very first experiment (id == b0) is always a snapshot.
    if new_id == ids.ROOT:
        return ("snapshot", "")
    # If the parent doesn't actually exist on disk yet (only the case for the
    # first experiment), still produce a snapshot.
    if parent_id == ids.ROOT and not storage.exists(parent_id, base):
        return ("snapshot", "")

    # Auto-checkpoint: if too many diffs since the last snapshot, snapshot.
    cfg = storage.load_config(base)
    threshold = int(cfg.get("auto_checkpoint_after", storage.DEFAULT_AUTO_CHECKPOINT_AFTER))
    chain = storage.chain_to_snapshot(parent_id, base)
    diffs_since_snapshot = len(chain) - 1  # chain[0] is the snapshot itself
    if threshold > 0 and diffs_since_snapshot >= threshold:
        info(
            f"auto-checkpoint: {diffs_since_snapshot} diffs since last snapshot "
            f"(threshold {threshold}) → creating snapshot"
        )
        return ("snapshot", "")

    # Build the diff text against the parent.
    patch_text = diffmod.make_unified_diff(parent_files, current_files)
    return ("diff", patch_text)
