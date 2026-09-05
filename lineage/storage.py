"""Storage layer for lineage.

Handles the on-disk layout under ``.lineage/`` and the atomic read/write of
``meta.json`` and other experiment artifacts.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import ids
from .errors import (
    ExperimentExistsError,
    ExperimentNotFoundError,
    InvalidIdError,
    LineageError,
)

LINEAGE_DIR = Path(".lineage")
EXPERIMENTS_DIRNAME = "experiments"
SNAPSHOT_DIRNAME = "snapshot"
DIFF_FILENAME = "diff.patch"
META_FILENAME = "meta.json"
NOTES_FILENAME = "notes.md"
GITIGNORE_MARKER = ".lineage/"
CONFIG_FILENAME = "config.json"

DEFAULT_AUTO_CHECKPOINT_AFTER = 10


@dataclass
class Meta:
    """Metadata for a single experiment."""

    id: str
    parent: str
    type: str  # "snapshot" or "diff"
    message: str = ""
    created_at: str = ""
    metrics: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Meta":
        return cls(
            id=data["id"],
            parent=data["parent"],
            type=data["type"],
            message=data.get("message", ""),
            created_at=data.get("created_at", ""),
            metrics={str(k): str(v) for k, v in data.get("metrics", {}).items()},
            tags=list(data.get("tags", [])),
        )


def now_iso() -> str:
    """Return the current time as an ISO-8601 string in UTC."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def lineage_root(root: Path | None = None) -> Path:
    """Return the path to the ``.lineage`` directory under ``root`` (default: CWD)."""
    base = Path(root) if root is not None else Path.cwd()
    return base / LINEAGE_DIR


def experiments_dir(root: Path | None = None) -> Path:
    """Return the path to the ``experiments`` directory under ``root``."""
    return lineage_root(root) / EXPERIMENTS_DIRNAME


def exp_dir(exp_id: str, root: Path | None = None) -> Path:
    """Return the path to an experiment's directory."""
    return experiments_dir(root) / exp_id


def snapshot_dir(exp_id: str, root: Path | None = None) -> Path:
    return exp_dir(exp_id, root) / SNAPSHOT_DIRNAME


def diff_path(exp_id: str, root: Path | None = None) -> Path:
    return exp_dir(exp_id, root) / DIFF_FILENAME


def meta_path(exp_id: str, root: Path | None = None) -> Path:
    return exp_dir(exp_id, root) / META_FILENAME


def notes_path(exp_id: str, root: Path | None = None) -> Path:
    return exp_dir(exp_id, root) / NOTES_FILENAME


def ensure_initialized(root: Path | None = None) -> Path:
    """Create ``.lineage/`` if needed, update ``.gitignore``, return the lineage root."""
    lr = lineage_root(root)
    lr.mkdir(parents=True, exist_ok=True)
    (lr / EXPERIMENTS_DIRNAME).mkdir(exist_ok=True)
    _ensure_gitignore(root)
    _ensure_config(root)
    return lr


def _ensure_gitignore(root: Path | None) -> None:
    base = Path(root) if root is not None else Path.cwd()
    gi = base / ".gitignore"
    needs_entry = True
    if gi.exists():
        try:
            existing = gi.read_text(encoding="utf-8").splitlines()
        except OSError:
            existing = []
        if GITIGNORE_MARKER in existing or "/.lineage/" in existing:
            needs_entry = False
        elif any(line.strip() == ".lineage" for line in existing):
            needs_entry = False
    if not needs_entry:
        return
    with _open_atomic_append(gi) as fh:
        if gi.exists() and gi.stat().st_size > 0:
            fh.write("\n")
        fh.write("# lineage\n")
        fh.write(f"{GITIGNORE_MARKER}\n")


def _open_atomic_append(path: Path):
    """Open a file in append mode, returning a context manager."""
    return open(path, "a", encoding="utf-8")


def _ensure_config(root: Path | None) -> None:
    base = Path(root) if root is not None else Path.cwd()
    cfg = lineage_root(base) / CONFIG_FILENAME
    if cfg.exists():
        return
    cfg.write_text(
        json.dumps(
            {
                "auto_checkpoint_after": DEFAULT_AUTO_CHECKPOINT_AFTER,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def load_config(root: Path | None = None) -> dict:
    base = Path(root) if root is not None else Path.cwd()
    cfg = lineage_root(base) / CONFIG_FILENAME
    if not cfg.exists():
        return {"auto_checkpoint_after": DEFAULT_AUTO_CHECKPOINT_AFTER}
    try:
        return json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"auto_checkpoint_after": DEFAULT_AUTO_CHECKPOINT_AFTER}


def is_initialized(root: Path | None = None) -> bool:
    return lineage_root(root).is_dir()


def list_ids(root: Path | None = None) -> list[str]:
    """Return all experiment ids under ``root``, sorted by id length then id."""
    ed = experiments_dir(root)
    if not ed.is_dir():
        return []
    ids_found: list[str] = []
    for p in ed.iterdir():
        if p.is_dir() and ids.is_valid_id(p.name):
            ids_found.append(p.name)
    ids_found.sort(key=lambda x: (len(x), x))
    return ids_found


def exists(exp_id: str, root: Path | None = None) -> bool:
    if not ids.is_valid_id(exp_id):
        return False
    return exp_dir(exp_id, root).is_dir()


def children_of(parent: str, root: Path | None = None) -> list[str]:
    """Return direct child ids of ``parent`` (nodes whose meta parent is ``parent``)."""
    if not ids.is_valid_id(parent):
        raise InvalidIdError(parent)
    out: list[str] = []
    for cid in list_ids(root):
        if cid == parent:
            continue
        try:
            if load(cid, root).parent == parent:
                out.append(cid)
        except (ExperimentNotFoundError, LineageError):
            continue
    return out


def load(exp_id: str, root: Path | None = None) -> Meta:
    """Load the meta for ``exp_id``."""
    if not exists(exp_id, root):
        raise ExperimentNotFoundError(f"Experiment not found: {exp_id}")
    p = meta_path(exp_id, root)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except OSError as e:
        raise LineageError(f"Could not read {p}: {e}") from e
    return Meta.from_dict(data)


def save(meta: Meta, root: Path | None = None) -> None:
    """Atomically save the meta for an experiment. Creates the experiment dir."""
    if not ids.is_valid_id(meta.id):
        raise InvalidIdError(meta.id)
    d = exp_dir(meta.id, root)
    d.mkdir(parents=True, exist_ok=True)
    p = meta_path(meta.id, root)
    write_text_atomic(p, json.dumps(meta.to_dict(), indent=2) + "\n")


def write_text_atomic(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (write tmp + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def create_experiment_dir(exp_id: str, root: Path | None = None) -> Path:
    """Create the experiment directory; raises if it already exists."""
    d = exp_dir(exp_id, root)
    if d.exists():
        raise ExperimentExistsError(f"Experiment already exists: {exp_id}")
    d.mkdir(parents=True, exist_ok=False)
    return d


def remove_experiment(exp_id: str, root: Path | None = None) -> None:
    """Remove an experiment's directory tree."""
    d = exp_dir(exp_id, root)
    if not d.exists():
        raise ExperimentNotFoundError(f"Experiment not found: {exp_id}")
    shutil.rmtree(d)


def rename_subtree(
    old_id: str, new_id: str, new_parent: str, root: Path | None = None
) -> dict[str, str]:
    """Rename ``old_id`` to ``new_id`` plus its whole descendant subtree.

    The subtree keeps its shape: each descendant gets ``<new ancestor path> +
    <next free letter>``. Metas are rewritten (new ids, remapped parents);
    the moved root's parent becomes ``new_parent``. Snapshot/diff/notes move
    along with the directories.

    Returns the ``{old_id: new_id}`` mapping. Raises ``LineageError`` if a
    target directory already exists.
    """
    if not exists(old_id, root):
        raise ExperimentNotFoundError(f"Experiment not found: {old_id}")
    # BFS from the old root: parents before children.
    order = [old_id]
    i = 0
    while i < len(order):
        order.extend(sorted(children_of(order[i], root), key=ids.sort_key))
        i += 1
    moving = set(order)
    old_metas = {cid: load(cid, root) for cid in order}

    mapping = {old_id: new_id}
    assigned: dict[str, set[str]] = {}
    for old in order[1:]:
        parent_new = mapping[old_metas[old].parent]
        blocked = {
            cid[len(parent_new):]
            for cid in list_ids(root)
            if cid not in moving
            and cid.startswith(parent_new)
            and len(cid) == len(parent_new) + 1
        } | assigned.get(parent_new, set())
        for ch in ids.CHILD_ALPHABET:
            candidate = parent_new + ch
            if ch not in blocked and not exp_dir(candidate, root).exists():
                mapping[old] = candidate
                assigned.setdefault(parent_new, set()).add(ch)
                break
        else:
            raise LineageError(
                f"Cannot rename under {parent_new}: all 26 child slots (a-z) taken"
            )

    for old, new in mapping.items():
        target = exp_dir(new, root)
        if old != new and target.exists():
            raise LineageError(f"Cannot rename {old} to {new}: target exists")
    for old, new in mapping.items():
        if old != new:
            exp_dir(old, root).rename(exp_dir(new, root))

    for old, new in mapping.items():
        m = old_metas[old]
        m.id = new
        m.parent = new_parent if old == old_id else mapping[m.parent]
        save(m, root)
    return mapping


def read_notes(exp_id: str, root: Path | None = None) -> str:
    p = notes_path(exp_id, root)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def write_notes(exp_id: str, text: str, root: Path | None = None) -> None:
    write_text_atomic(notes_path(exp_id, root), text)


def find_latest(root: Path | None = None) -> str | None:
    """Return the most recently created experiment id, or None if none exist."""
    all_ids = list_ids(root)
    if not all_ids:
        return None
    latest_id = None
    latest_key: tuple[str, tuple[int, object]] = ("", (0, 0))
    for cid in all_ids:
        try:
            m = load(cid, root)
        except (ExperimentNotFoundError, LineageError):
            continue
        # Tie-break same-second timestamps by id so rapid successive
        # `add`s keep chaining instead of all parenting the first node.
        key = (m.created_at, ids.sort_key(cid))
        if key > latest_key:
            latest_key = key
            latest_id = cid
    return latest_id


def find_latest_leaf(root: Path | None = None) -> str | None:
    """Return the most recently created experiment that has no children."""
    all_ids = list_ids(root)
    candidates: list[str] = []
    for cid in all_ids:
        if not children_of(cid, root):
            candidates.append(cid)
    if not candidates:
        return None
    candidates.sort(key=lambda c: load(c, root).created_at)
    return candidates[-1]


def chain_to_snapshot(exp_id: str, root: Path | None = None) -> list[str]:
    """Return the chain ``[snapshot, ..., exp_id]`` by following meta parents.

    The first element is the nearest snapshot ancestor of ``exp_id`` (or ``exp_id``
    itself if it is a snapshot).
    """
    if not exists(exp_id, root):
        raise ExperimentNotFoundError(f"Experiment not found: {exp_id}")
    chain: list[str] = [exp_id]
    cur = exp_id
    while True:
        m = load(cur, root)
        if m.type == "snapshot":
            chain.reverse()
            return chain
        if m.parent == cur or m.parent == ids.ROOT and cur == ids.ROOT:
            # Defensive: parentless diff (shouldn't happen)
            chain.reverse()
            return chain
        chain.append(m.parent)
        cur = m.parent


def temp_dir(prefix: str = "lineage-") -> Path:
    """Return a unique temporary directory (caller is responsible for cleanup)."""
    name = f"{prefix}{uuid.uuid4().hex[:8]}"
    return Path(tempfile.mkdtemp(prefix=name))
