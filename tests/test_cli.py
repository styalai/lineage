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


def test_add_from_creates_diff(workdir):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    r1 = run(workdir, "add", "-m", "v0")
    assert r1.returncode == 0
    (workdir / "a.txt").write_text("v1\n", encoding="utf-8")
    r2 = run(workdir, "add", "-m", "v1", "--from", "b0")
    assert r2.returncode == 0
    # Attached under b0: path-encoded id, diff vs the parent.
    assert (workdir / ".lineage" / "experiments" / "b0a" / "diff.patch").is_file()
    assert not (workdir / ".lineage" / "experiments" / "b0a" / "snapshot").exists()


def test_bare_adds_float_as_sequential_baselines(workdir):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    assert run(workdir, "add", "-m", "v0").returncode == 0
    (workdir / "a.txt").write_text("v1\n", encoding="utf-8")
    assert run(workdir, "add", "-m", "v1").returncode == 0
    (workdir / "a.txt").write_text("v2\n", encoding="utf-8")
    assert run(workdir, "add", "-m", "v2").returncode == 0
    for cid in ("b1", "b2"):
        meta = (workdir / ".lineage" / "experiments" / cid / "meta.json").read_text()
        assert '"type": "snapshot"' in meta
        assert f'"parent": "{cid}"' in meta
        assert (workdir / ".lineage" / "experiments" / cid / "snapshot").is_dir()


def test_add_snapshot_flag_creates_baseline(workdir):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    r1 = run(workdir, "add", "-m", "v0")
    assert r1.returncode == 0
    (workdir / "a.txt").write_text("v1\n", encoding="utf-8")
    r2 = run(workdir, "add", "-m", "v1", "--snapshot")
    assert r2.returncode == 0, r2.stderr
    assert (workdir / ".lineage" / "experiments" / "b1" / "snapshot" / "a.txt").is_file()
    meta = (workdir / ".lineage" / "experiments" / "b1" / "meta.json").read_text()
    assert '"type": "snapshot"' in meta


def test_add_detached_creates_floating_baseline(workdir):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    r1 = run(workdir, "add", "-m", "v0")
    assert r1.returncode == 0
    (workdir / "a.txt").write_text("v1\n", encoding="utf-8")
    r2 = run(workdir, "add", "-m", "v1", "--detached")
    assert r2.returncode == 0, r2.stderr
    assert "floating" in r2.stdout
    assert (workdir / ".lineage" / "experiments" / "b1" / "snapshot" / "a.txt").is_file()
    meta = (workdir / ".lineage" / "experiments" / "b1" / "meta.json").read_text()
    assert '"type": "snapshot"' in meta
    assert '"parent": "b1"' in meta


def test_add_respects_from(workdir):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    run(workdir, "add", "-m", "v0")
    (workdir / "a.txt").write_text("v1\n", encoding="utf-8")
    run(workdir, "add", "-m", "v1")
    # Now b0a should be attached under b0 with a path-encoded id.
    (workdir / "a.txt").write_text("v2\n", encoding="utf-8")
    r = run(workdir, "add", "-m", "v2", "--from", "b0")
    assert r.returncode == 0
    meta = (workdir / ".lineage" / "experiments" / "b0a" / "meta.json").read_text()
    assert '"parent": "b0"' in meta


def test_diff_between_experiments(workdir):
    (workdir / "a.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    run(workdir, "add", "-m", "v0")
    (workdir / "a.txt").write_text("one\nTWO\nthree\n", encoding="utf-8")
    run(workdir, "add", "-m", "v1")
    r = run(workdir, "diff", "b1", "b0")
    assert r.returncode == 0
    assert "-two" in r.stdout
    assert "+TWO" in r.stdout


def test_diff_against_parent(workdir):
    (workdir / "a.txt").write_text("one\n", encoding="utf-8")
    run(workdir, "add", "-m", "v0")
    (workdir / "a.txt").write_text("two\n", encoding="utf-8")
    run(workdir, "add", "-m", "v1", "--from", "b0")
    r = run(workdir, "diff", "b0a")
    assert r.returncode == 0
    assert "-one" in r.stdout
    assert "+two" in r.stdout


def test_diff_stat(workdir):
    (workdir / "a.txt").write_text("a\n", encoding="utf-8")
    run(workdir, "add", "-m", "v0")
    (workdir / "a.txt").write_text("b\n", encoding="utf-8")
    (workdir / "new.txt").write_text("n\n", encoding="utf-8")
    run(workdir, "add", "-m", "v1", "--from", "b0")
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
    run(workdir, "add", "-m", "v1", "--from", "b0")
    r = run(workdir, "remove", "b0")
    assert r.returncode != 0
    assert (workdir / ".lineage" / "experiments" / "b0").is_dir()


def test_remove_recursive(workdir):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    run(workdir, "add", "-m", "v0")
    (workdir / "a.txt").write_text("v1\n", encoding="utf-8")
    run(workdir, "add", "-m", "v1", "--from", "b0")
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
    assert '"loss": "2.91"' in meta
    assert '"acc": "0.81"' in meta


def test_log_accepts_string_values(workdir):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    run(workdir, "add", "-m", "v0")
    r = run(
        workdir, "log", "b0",
        "dataset=imagenet", "best=true", "notes='final run'",
    )
    assert r.returncode == 0, r.stderr
    meta = (workdir / ".lineage" / "experiments" / "b0" / "meta.json").read_text()
    assert '"dataset": "imagenet"' in meta
    assert '"best": "true"' in meta
    assert '"notes": "final run"' in meta


def test_log_accepts_arbitrary_key_names(workdir):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    run(workdir, "add", "-m", "v0")
    r = run(
        workdir, "log", "b0",
        "val/loss=1.2", "x.y.z=ok", "with-dash=42",
    )
    assert r.returncode == 0, r.stderr
    meta = (workdir / ".lineage" / "experiments" / "b0" / "meta.json").read_text()
    assert '"val/loss": "1.2"' in meta
    assert '"x.y.z": "ok"' in meta
    assert '"with-dash": "42"' in meta


def test_log_rejects_invalid_key(workdir):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    run(workdir, "add", "-m", "v0")
    r = run(workdir, "log", "b0", "1bad=value")
    assert r.returncode != 0
    r2 = run(workdir, "log", "b0", "no-value")
    assert r2.returncode != 0


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


def test_init_requires_for(workdir):
    r = run(workdir, "init")
    assert r.returncode != 0


def test_init_writes_all_tool_files(workdir):
    r = run(workdir, "init", "--for", "all")
    assert r.returncode == 0, r.stderr
    agents = workdir / "AGENTS.md"
    claude = workdir / "CLAUDE.md"
    assert agents.is_file() and claude.is_file()
    # Same instructions everywhere, matching the shipped template.
    template = (REPO_ROOT / "AGENTS.md").read_text()
    assert agents.read_text() == template
    assert claude.read_text() == template


def test_init_for_single_tool(workdir):
    r = run(workdir, "init", "--for", "claude")
    assert r.returncode == 0, r.stderr
    assert (workdir / "CLAUDE.md").is_file()
    assert not (workdir / "AGENTS.md").exists()


def test_init_refuses_existing_without_force(workdir):
    (workdir / "AGENTS.md").write_text("mine\n", encoding="utf-8")
    r = run(workdir, "init", "--for", "opencode")
    assert r.returncode != 0
    assert (workdir / "AGENTS.md").read_text() == "mine\n"


def test_init_force_overwrites(workdir):
    (workdir / "AGENTS.md").write_text("mine\n", encoding="utf-8")
    r = run(workdir, "init", "--for", "opencode", "--force")
    assert r.returncode == 0, r.stderr
    assert "lineage add" in (workdir / "AGENTS.md").read_text()


def test_init_is_idempotent(workdir):
    assert run(workdir, "init", "--for", "all").returncode == 0
    r = run(workdir, "init", "--for", "all")
    assert r.returncode == 0, r.stderr
    assert "up to date" in r.stdout
