"""Tests for snapshot and reconstruction."""

from __future__ import annotations

from lineage import diff, reconstruct, snapshot, storage
from conftest import write


def _add_with_files(root, files: dict[str, str], message: str = "", parent: str | None = None) -> str:
    """Helper: simulate `lineage add` against an in-memory file map."""
    storage.ensure_initialized(root)
    for rel, data in files.items():
        write(root / rel, data)

    from lineage import ids, workspace

    current = workspace.gather_files(root)
    existing = storage.list_ids(root)
    if not existing:
        new_id = ids.ROOT
    else:
        parent_id = parent or (storage.find_latest(root) or ids.ROOT)
        new_id = ids.next_experiment_id(existing)

    storage.create_experiment_dir(new_id, root)

    if new_id == ids.ROOT:
        parent_id = ids.ROOT
        parent_files: dict[str, bytes] = {}
    elif not storage.exists(parent_id, root):
        parent_files = {}
    else:
        parent_files = reconstruct.reconstruct_files(parent_id, root)

    if new_id == ids.ROOT or (
        parent_id == ids.ROOT and not storage.exists(parent_id, root)
    ):
        exp_type = "snapshot"
        patch_text = ""
    else:
        exp_type = "diff"
        patch_text = diff.make_unified_diff(parent_files, current)

    meta = storage.Meta(
        id=new_id,
        parent=parent_id,
        type=exp_type,
        message=message,
        created_at=storage.now_iso(),
    )
    storage.save(meta, root)
    storage.write_notes(new_id, f"# {new_id}\n", root)
    if exp_type == "snapshot":
        snapshot.create_snapshot(root, storage.snapshot_dir(new_id, root))
    else:
        storage.write_text_atomic(storage.diff_path(new_id, root), patch_text)
    return new_id


def test_snapshot_roundtrip(workdir):
    write(workdir / "src" / "main.py", "print('a')\n")
    write(workdir / "README.md", "hello\n")
    sid = _add_with_files(workdir, {}, message="init")
    assert sid == "b0"
    files = snapshot.list_snapshot_files(storage.snapshot_dir(sid, workdir))
    assert files["src/main.py"] == b"print('a')\n"
    assert files["README.md"] == b"hello\n"


def test_diff_then_reconstruct(workdir):
    write(workdir / "a.txt", "one\ntwo\nthree\n")
    sid = _add_with_files(workdir, {}, message="init")
    # modify
    write(workdir / "a.txt", "one\nTWO\nthree\n")
    write(workdir / "b.txt", "new\n")
    cid = _add_with_files(workdir, {}, message="modify", parent=sid)
    assert cid == "b1"
    files = reconstruct.reconstruct_files(cid, workdir)
    assert files["a.txt"] == b"one\nTWO\nthree\n"
    assert files["b.txt"] == b"new\n"


def test_chain_reconstruction(workdir):
    write(workdir / "x.txt", "v0\n")
    a = _add_with_files(workdir, {}, message="v0")
    write(workdir / "x.txt", "v1\n")
    b = _add_with_files(workdir, {}, message="v1", parent=a)
    write(workdir / "x.txt", "v2\n")
    c = _add_with_files(workdir, {}, message="v2", parent=b)
    assert reconstruct.reconstruct_files(a, workdir)["x.txt"] == b"v0\n"
    assert reconstruct.reconstruct_files(b, workdir)["x.txt"] == b"v1\n"
    assert reconstruct.reconstruct_files(c, workdir)["x.txt"] == b"v2\n"


def test_snapshot_dir_excluded_from_workspace(workdir):
    write(workdir / "a.txt", "a\n")
    sid = _add_with_files(workdir, {}, message="init")
    from lineage import workspace
    files = workspace.gather_files(workdir)
    assert ".lineage" not in files
    assert all(not p.startswith(".lineage/") for p in files)
    assert files["a.txt"] == b"a\n"


def test_reconstruct_after_deletion(workdir):
    write(workdir / "a.txt", "a\n")
    sid = _add_with_files(workdir, {}, message="init")
    (workdir / "a.txt").unlink()
    cid = _add_with_files(workdir, {}, message="delete", parent=sid)
    files = reconstruct.reconstruct_files(cid, workdir)
    assert "a.txt" not in files
