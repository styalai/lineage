"""Tests for lineage/ids.py."""

from __future__ import annotations

from lineage import ids


def test_root_is_b0():
    assert ids.ROOT == "b0"


def test_is_valid_id_accepts_sequential_ids():
    assert ids.is_valid_id("b0")
    assert ids.is_valid_id("b1")
    assert ids.is_valid_id("b2")
    assert ids.is_valid_id("b10")
    assert ids.is_valid_id("b123")
    assert not ids.is_valid_id("")
    assert not ids.is_valid_id("a")
    assert not ids.is_valid_id("B1")
    assert not ids.is_valid_id("b")
    assert not ids.is_valid_id("1")
    assert not ids.is_valid_id("b1A")  # nested suffixes are lowercase only
    assert not ids.is_valid_id("b1!")
    assert not ids.is_valid_id("b 1")


def test_is_valid_id_accepts_path_ids():
    # Attached nodes encode their position: parent id + letters.
    assert ids.is_valid_id("b0a")
    assert ids.is_valid_id("b0aa")
    assert ids.is_valid_id("b2a")
    assert ids.is_valid_id("b21z")
    assert ids.is_valid_id("b21")  # reads as floating number 21, unambiguous
    # Digits after letters would be ambiguous, so they're rejected.
    assert not ids.is_valid_id("b2a1")


def test_is_valid_id_still_accepts_legacy_prefix_ids():
    # Workspaces created before sequential numbering keep loading.
    assert ids.is_valid_id("b0a")
    assert ids.is_valid_id("b0ab0")
    assert ids.is_valid_id("b0@")
    assert ids.is_valid_id("b0!")
    assert ids.is_valid_id("b09")
    assert not ids.is_valid_id("b0A")  # uppercase was never valid
    assert not ids.is_valid_id("b0a b")


def test_next_experiment_id_starts_at_b1():
    assert ids.next_experiment_id([]) == "b1"
    assert ids.next_experiment_id(["b0"]) == "b1"


def test_next_experiment_id_increments_past_max():
    assert ids.next_experiment_id(["b0", "b1", "b2"]) == "b3"
    # Order of input doesn't matter.
    assert ids.next_experiment_id(["b2", "b0", "b1"]) == "b3"


def test_next_experiment_id_never_reuses_deleted_numbers():
    assert ids.next_experiment_id(["b0", "b2"]) == "b3"


def test_next_experiment_id_goes_past_b9_numerically():
    assert ids.next_experiment_id(["b0", "b9", "b10"]) == "b11"


def test_next_experiment_id_ignores_legacy_ids():
    assert ids.next_experiment_id(["b0", "b0a", "b0b"]) == "b1"
    assert ids.next_experiment_id(["b0", "b0a", "b1"]) == "b2"


def test_next_child_id_allocates_path_suffix():
    assert ids.next_child_id("b0", ["b0"]) == "b0a"
    assert ids.next_child_id("b0", ["b0", "b0a"]) == "b0b"
    assert ids.next_child_id("b2", ["b0", "b1", "b2"]) == "b2a"
    # Floating bN children attached via meta links don't block suffix slots.
    assert ids.next_child_id("b0", ["b0", "b1"]) == "b0a"


def test_next_child_id_exhaustion_raises():
    from lineage.errors import LineageError

    taken = ["b0"] + ["b0" + c for c in ids.CHILD_ALPHABET]
    try:
        ids.next_child_id("b0", taken)
    except LineageError as e:
        assert "26" in str(e)
    else:
        raise AssertionError("expected LineageError")


def test_next_experiment_id_ignores_path_ids():
    assert ids.next_experiment_id(["b0", "b0a", "b0b"]) == "b1"
    assert ids.next_experiment_id(["b0", "b1", "b2a"]) == "b2"
