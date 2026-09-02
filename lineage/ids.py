"""Experiment IDs and the 42-character alphabet.

Root experiment is ``b0``. Each level appends a single character from
``ALPHABET``. Parent is inferred by stripping the last character.

Example::

    b0
    └── b0a
        ├── b0aa
        └── b0ab
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .errors import InvalidIdError, MaxChildrenError

ALPHABET: str = "abcdefghijklmnopqrstuvwxyz@#&?%!0123456789"
"""42-character alphabet used to encode the lineage path."""

ROOT: str = "b0"
"""The root experiment id."""

_MAX_CHILDREN: int = len(ALPHABET)  # 42

_VALID_RE = re.compile(r"^b0[abcdefghijklmnopqrstuvwxyz@#&?%!0123456789]*$")


def is_valid_id(exp_id: str) -> bool:
    """Return True if ``exp_id`` is a syntactically valid experiment id."""
    return isinstance(exp_id, str) and bool(_VALID_RE.match(exp_id))


def parent_of(exp_id: str) -> str:
    """Return the parent id of ``exp_id``.

    The parent of the root ``b0`` is itself (callers should special-case this).
    """
    if not is_valid_id(exp_id):
        raise InvalidIdError(f"Invalid experiment id: {exp_id!r}")
    if exp_id == ROOT:
        return ROOT
    return exp_id[:-1]


def is_ancestor(maybe_ancestor: str, exp_id: str) -> bool:
    """Return True if ``maybe_ancestor`` is an ancestor (or equal) of ``exp_id``."""
    if not (is_valid_id(maybe_ancestor) and is_valid_id(exp_id)):
        return False
    if maybe_ancestor == ROOT:
        return True
    return exp_id == maybe_ancestor or exp_id.startswith(maybe_ancestor)


def child_char_at(index: int) -> str:
    """Return the alphabet character at the given child index (0..41)."""
    if not 0 <= index < _MAX_CHILDREN:
        raise IndexError(f"child index out of range: {index}")
    return ALPHABET[index]


def next_child_id(parent: str, existing_children: Iterable[str]) -> str:
    """Return the next child id of ``parent`` not already in ``existing_children``.

    Raises ``MaxChildrenError`` if all 42 slots are taken.
    """
    if not is_valid_id(parent):
        raise InvalidIdError(f"Invalid parent id: {parent!r}")
    used = {c[-1] for c in existing_children if c.startswith(parent) and len(c) == len(parent) + 1}
    for i, ch in enumerate(ALPHABET):
        if ch not in used:
            return parent + ch
    raise MaxChildrenError(parent)


def validate_child(parent: str, child: str) -> None:
    """Validate that ``child`` is a direct child of ``parent``."""
    if not is_valid_id(child):
        raise InvalidIdError(f"Invalid child id: {child!r}")
    if parent == ROOT:
        if not child.startswith(ROOT) or len(child) <= len(ROOT):
            raise InvalidIdError(f"{child!r} is not a child of {parent!r}")
        return
    if not child.startswith(parent) or len(child) != len(parent) + 1:
        raise InvalidIdError(f"{child!r} is not a child of {parent!r}")
