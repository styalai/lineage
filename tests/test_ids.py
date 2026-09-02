"""Tests for lineage/ids.py."""

from __future__ import annotations

import pytest

from lineage import ids
from lineage.errors import InvalidIdError, MaxChildrenError


def test_alphabet_length_is_42():
    assert len(ids.ALPHABET) == 42


def test_alphabet_order_matches_spec():
    assert ids.ALPHABET == "abcdefghijklmnopqrstuvwxyz@#&?%!0123456789"


def test_root_is_b0():
    assert ids.ROOT == "b0"


def test_is_valid_id():
    assert ids.is_valid_id("b0")
    assert ids.is_valid_id("b0a")
    assert ids.is_valid_id("b0ab0")
    assert ids.is_valid_id("b0@")
    assert ids.is_valid_id("b0!")
    assert ids.is_valid_id("b09")
    assert not ids.is_valid_id("")
    assert not ids.is_valid_id("a")
    assert not ids.is_valid_id("b1")
    assert not ids.is_valid_id("B0")
    assert not ids.is_valid_id("b0A")  # uppercase not in alphabet
    assert not ids.is_valid_id("b0 ")
    assert not ids.is_valid_id("b0a b")


def test_parent_of():
    assert ids.parent_of("b0a") == "b0"
    assert ids.parent_of("b0ab") == "b0a"
    assert ids.parent_of("b0a!") == "b0a"
    assert ids.parent_of("b0") == "b0"


def test_parent_of_invalid_id_raises():
    with pytest.raises(InvalidIdError):
        ids.parent_of("bogus")


def test_is_ancestor():
    assert ids.is_ancestor("b0", "b0")
    assert ids.is_ancestor("b0", "b0a")
    assert ids.is_ancestor("b0", "b0ab0")
    assert ids.is_ancestor("b0a", "b0ab")
    assert not ids.is_ancestor("b0a", "b0")
    assert not ids.is_ancestor("b0a", "b0b")
    assert not ids.is_ancestor("b0ab", "b0a")


def test_next_child_id_uses_alphabet_order():
    parent = "b0"
    assert ids.next_child_id(parent, []) == "b0a"
    # Once 'a' is taken, next is 'b'.
    assert ids.next_child_id(parent, ["b0a"]) == "b0b"


def test_next_child_id_uses_full_alphabet_sequence():
    parent = "b0"
    # Simulate every character of the alphabet except the first.
    taken = ["b0" + c for c in ids.ALPHABET[1:]]
    assert ids.next_child_id(parent, taken) == "b0a"


def test_next_child_id_overflow():
    parent = "b0"
    all_children = ["b0" + c for c in ids.ALPHABET]
    with pytest.raises(MaxChildrenError):
        ids.next_child_id(parent, all_children)


def test_next_child_id_only_direct_children_count():
    parent = "b0"
    # 'b0ab' is a grandchild; doesn't block creating 'b0a'.
    assert ids.next_child_id(parent, ["b0ab"]) == "b0a"


def test_child_char_at():
    assert ids.child_char_at(0) == "a"
    assert ids.child_char_at(25) == "z"
    assert ids.child_char_at(26) == "@"
    assert ids.child_char_at(41) == "9"
    with pytest.raises(IndexError):
        ids.child_char_at(42)
    with pytest.raises(IndexError):
        ids.child_char_at(-1)
