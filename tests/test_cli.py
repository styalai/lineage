"""End-to-end CLI tests using subprocess against a temp workdir."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def run(workdir: Path, *args: str, expect: int = 0) -> subprocess.CompletedProcess:
    """Invoke `python -m lineage ...` with the given args, in ``workdir``."""
    env = os.environ.copy()
    # Make sure we use the local source, not anything installed system-wide.
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "lineage", *args],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_help(workdir):
    r = run(workdir, "--help")
    assert r.returncode == 0
    assert "usage:" in r.stdout.lower()


def test_version(workdir):
    r = run(workdir, "--version")
    assert r.returncode == 0
    assert r.stdout.strip().startswith("lineage")


def test_add_creates_b0_snapshot(workdir):
    (workdir / "src").mkdir()
    (workdir / "src" / "main.py").write_text("print('a')\n", encoding="utf-8")
    r = run(workdir, "add", "-m", "initial")
    assert r.returncode == 0, r.stderr
    assert (workdir / ".lineage" / "experiments" / "b0" / "snapshot" / "src" / "main.py").is_file()
    assert (workdir / ".lineage" / "experiments" / "b0" / "meta.json").is_file()


def test_add_second_creates_diff(workdir):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    r1 = run(workdir, "add", "-m", "v0")
    assert r1.returncode == 0
    (workdir / "a.txt").write_text("v1\n", encoding="utf-8")
    r2 = run(workdir, "add", "-m", "v1")
    assert r2.returncode == 0
    assert (workdir / ".lineage" / "experiments" / "b0a" / "diff.patch").is_file()
    assert not (workdir / ".lineage" / "experiments" / "b0a" / "snapshot").exists()


def test_add_respects_from(workdir):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    run(workdir, "add", "-m", "v0")
    (workdir / "a.txt").write_text("v1\n", encoding="utf-8")
    run(workdir, "add", "-m", "v1")
    # Now b0b should be a child of b0 (not b0a) when --from b0 is used.
    (workdir / "a.txt").write_text("v2\n", encoding="utf-8")
    r = run(workdir, "add", "-m", "v2", "--from", "b0")
    assert r.returncode == 0
    meta = (workdir / ".lineage" / "experiments" / "b0b" / "meta.json").read_text()
    assert '"parent": "b0"' in meta


def test_diff_between_experiments(workdir):
    (workdir / "a.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    run(workdir, "add", "-m", "v0")
    (workdir / "a.txt").write_text("one\nTWO\nthree\n", encoding="utf-8")
    run(workdir, "add", "-m", "v1")
    r = run(workdir, "diff", "b0a", "b0")
    assert r.returncode == 0
    assert "-two" in r.stdout
    assert "+TWO" in r.stdout


def test_diff_against_parent(workdir):
    (workdir / "a.txt").write_text("one\n", encoding="utf-8")
    run(workdir, "add", "-m", "v0")
    (workdir / "a.txt").write_text("two\n", encoding="utf-8")
    run(workdir, "add", "-m", "v1")
    r = run(workdir, "diff", "b0a")
    assert r.returncode == 0
    assert "-one" in r.stdout
    assert "+two" in r.stdout


def test_diff_stat(workdir):
    (workdir / "a.txt").write_text("a\n", encoding="utf-8")
    run(workdir, "add", "-m", "v0")
    (workdir / "a.txt").write_text("b\n", encoding="utf-8")
    (workdir / "new.txt").write_text("n\n", encoding="utf-8")
    run(workdir, "add", "-m", "v1")
    r = run(workdir, "diff", "--stat", "b0a")
    assert r.returncode == 0
    assert "modified:" in r.stdout
    assert "added:" in r.stdout


def test_revert_dry_run(workdir):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    run(workdir, "add", "-m", "v0")
    (workdir / "a.txt").write_text("v1\n", encoding="utf-8")
    run(workdir, "add", "-m", "v1")
    r = run(workdir, "revert", "b0", "--dry-run")
    assert r.returncode == 0
    assert "dry run" in r.stdout
    # File should still be v1 (dry-run).
    assert (workdir / "a.txt").read_text() == "v1\n"


def test_revert_restores_files(workdir):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    run(workdir, "add", "-m", "v0")
    (workdir / "a.txt").write_text("v1\n", encoding="utf-8")
    run(workdir, "add", "-m", "v1")
    r = run(workdir, "revert", "b0")
    assert r.returncode == 0, r.stderr
    assert (workdir / "a.txt").read_text() == "v0\n"


def test_remove_refuses_with_children(workdir):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    run(workdir, "add", "-m", "v0")
    (workdir / "a.txt").write_text("v1\n", encoding="utf-8")
    run(workdir, "add", "-m", "v1")
    r = run(workdir, "remove", "b0")
    assert r.returncode != 0
    assert (workdir / ".lineage" / "experiments" / "b0").is_dir()


def test_remove_recursive(workdir):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    run(workdir, "add", "-m", "v0")
    (workdir / "a.txt").write_text("v1\n", encoding="utf-8")
    run(workdir, "add", "-m", "v1")
    r = run(workdir, "remove", "--recursive", "b0")
    assert r.returncode == 0
    assert not (workdir / ".lineage" / "experiments" / "b0").exists()
    assert not (workdir / ".lineage" / "experiments" / "b0a").exists()


def test_log_writes_metric(workdir):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    run(workdir, "add", "-m", "v0")
    r = run(workdir, "log", "b0", "loss=2.91", "acc=0.81")
    assert r.returncode == 0, r.stderr
    meta = (workdir / ".lineage" / "experiments" / "b0" / "meta.json").read_text()
    assert '"loss": 2.91' in meta
    assert '"acc": 0.81' in meta


def test_log_rejects_non_numeric(workdir):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    run(workdir, "add", "-m", "v0")
    r = run(workdir, "log", "b0", "name=alice")
    assert r.returncode != 0


def test_note_via_message(workdir):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    run(workdir, "add", "-m", "v0")
    r = run(workdir, "note", "b0", "-m", "first thoughts")
    assert r.returncode == 0, r.stderr
    notes = (workdir / ".lineage" / "experiments" / "b0" / "notes.md").read_text()
    assert "first thoughts" in notes


def test_unknown_command(workdir):
    r = run(workdir, "nope")
    assert r.returncode != 0


def test_gitignore_created(workdir):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    run(workdir, "add", "-m", "v0")
    gi = workdir / ".gitignore"
    assert gi.is_file()
    text = gi.read_text()
    assert ".lineage/" in text.splitlines() or ".lineage" in text.splitlines()
