"""Tests for unified diff generation and application."""

from __future__ import annotations

import pytest

from lineage import diff
from lineage.diff import FileState
from lineage.errors import LineageError


def test_make_unified_diff_no_changes():
    a = {"x.txt": b"hello\n"}
    b = {"x.txt": b"hello\n"}
    assert diff.make_unified_diff(a, b) == ""


def test_make_unified_diff_modification():
    a = {"x.txt": b"line1\nline2\nline3\n"}
    b = {"x.txt": b"line1\nLINE2\nline3\n"}
    out = diff.make_unified_diff(a, b)
    assert "--- a/x.txt" in out
    assert "+++ b/x.txt" in out
    assert "-line2" in out
    assert "+LINE2" in out


def test_make_unified_diff_new_file():
    a: dict[str, bytes] = {}
    b = {"x.txt": b"hello\n"}
    out = diff.make_unified_diff(a, b)
    assert "--- /dev/null" in out
    assert "+++ b/x.txt" in out
    assert "+hello" in out


def test_make_unified_diff_deleted_file():
    a = {"x.txt": b"hello\n"}
    b: dict[str, bytes] = {}
    out = diff.make_unified_diff(a, b)
    assert "--- a/x.txt" in out
    assert "+++ /dev/null" in out
    assert "-hello" in out


def test_make_unified_diff_binary_skipped():
    a = {"x.bin": bytes(range(256))}
    b = {"x.bin": bytes(reversed(range(256)))}
    out = diff.make_unified_diff(a, b)
    # Binary files differ, exact hunk shape doesn't matter; we just verify
    # the applier won't accept it.
    assert "Binary files" in out


def test_apply_patch_text_modify():
    state = FileState(files={"x.txt": b"line1\nline2\nline3\n"})
    patch = diff.make_unified_diff(
        state.files, {"x.txt": b"line1\nLINE2\nline3\n"}
    )
    diff.apply_patch_text(state, patch)
    assert state.files["x.txt"] == b"line1\nLINE2\nline3\n"


def test_apply_patch_text_new_file():
    state = FileState(files={})
    patch = diff.make_unified_diff({}, {"x.txt": b"hello\n"})
    diff.apply_patch_text(state, patch)
    assert state.files["x.txt"] == b"hello\n"


def test_apply_patch_text_delete_file():
    state = FileState(files={"x.txt": b"hello\n"})
    patch = diff.make_unified_diff({"x.txt": b"hello\n"}, {})
    diff.apply_patch_text(state, patch)
    assert "x.txt" not in state.files


def test_apply_patch_text_reverse():
    state = FileState(files={"x.txt": b"line1\nline2\nline3\n"})
    target = {"x.txt": b"line1\nLINE2\nline3\n"}
    forward = diff.make_unified_diff(state.files, target)
    diff.apply_patch_text(state, forward)
    assert state.files["x.txt"] == target["x.txt"]
    # Now reverse.
    diff.apply_patch_text(state, forward, reverse=True)
    assert state.files["x.txt"] == b"line1\nline2\nline3\n"


def test_apply_patch_text_multiple_hunks():
    a = {"x.txt": b"a\nb\nc\nd\ne\nf\ng\nh\ni\nj\nk\n"}
    b = {"x.txt": b"a\nb\nC\nd\ne\nf\ng\nH\ni\nj\nk\n"}
    forward = diff.make_unified_diff(a, b)
    state = FileState(files=dict(a))
    diff.apply_patch_text(state, forward)
    assert state.files["x.txt"] == b["x.txt"]
    diff.apply_patch_text(state, forward, reverse=True)
    assert state.files["x.txt"] == a["x.txt"]


def test_apply_patch_text_multi_file():
    a = {"a.txt": b"a\n", "b.txt": b"b\n"}
    b = {"a.txt": b"A\n", "c.txt": b"c\n"}
    forward = diff.make_unified_diff(a, b)
    state = FileState(files=dict(a))
    diff.apply_patch_text(state, forward)
    assert state.files == b


def test_apply_patch_text_binary_raises():
    state = FileState(files={"x.bin": b"abc"})
    patch = "--- a/x.bin\n+++ b/x.bin\nBinary files a/x.bin and b/x.bin differ\n"
    with pytest.raises(LineageError):
        diff.apply_patch_text(state, patch)
