"""Experiment IDs: floating ``bN`` numbers and position-reflecting paths.

- The root is ``b0``. New experiments start life floating (no parent) as
  the next integer: ``b1``, ``b2``, ... Parentage lives in ``meta.json``.
- Attaching a node under a parent renames it to a path id: the parent id
  plus one lowercase letter (``b0a``, ``b2a``, ``b0aa``, ...). Detaching
  renames back to a fresh ``bN``. So an attached node's id always reflects
  its current position; floating nodes are always ``bN``.
- Workspaces predating this scheme (flat ``bN`` children with meta parents,
  or old 42-char-alphabet suffixes) remain valid and loadable.

Nested suffixes are letters only: digits would be ambiguous with ``bN``
(``b21`` must read as number 21, never "child 1 of b2").
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .errors import LineageError

ROOT: str = "b0"
"""The root experiment id."""

CHILD_ALPHABET: str = "abcdefghijklmnopqrstuvwxyz"
"""Suffix characters for nested levels (26 slots per parent)."""

_NEW_RE = re.compile(r"^b\d+[a-z]*$")
_LEGACY_RE = re.compile(r"^b0[abcdefghijklmnopqrstuvwxyz@#&?%!0123456789]*$")


def is_valid_id(exp_id: str) -> bool:
    """Return True if ``exp_id`` is a syntactically valid experiment id."""
    return isinstance(exp_id, str) and bool(
        _NEW_RE.match(exp_id) or _LEGACY_RE.match(exp_id)
    )


_NUM_RE = re.compile(r"^b(\d+)$")


def _floating_number(exp_id: str) -> int | None:
    """Return N if ``exp_id`` is a floating ``bN`` id, else None."""
    m = _NUM_RE.match(exp_id or "")
    return int(m.group(1)) if m else None


def next_experiment_id(existing_ids: Iterable[str]) -> str:
    """Return the next ``bN`` id after the highest floating number in use.

    Path-style (nested) and legacy ids are ignored for numbering, so a
    workspace holding only ``b0`` yields ``b1``. Deleted numbers are never
    reused; a number freed by a rename may be reclaimed.
    """
    top = 0
    for eid in existing_ids:
        n = _floating_number(eid)
        if n is not None:
            top = max(top, n)
    return f"b{top + 1}"


def sort_key(exp_id: str) -> tuple[int, object]:
    """Order floating ``bN`` ids numerically; anything else sorts after, lexically."""
    n = _floating_number(exp_id)
    if n is not None:
        return (0, n)
    return (1, exp_id or "")


def next_child_id(parent: str, existing_ids: Iterable[str]) -> str:
    """Return the next free path id directly under ``parent``.

    The id is ``parent`` plus the first unused letter of ``CHILD_ALPHABET``.
    Only prefix children (``parent + one letter``) block a slot; floating
    ``bN`` nodes attached via meta links don't occupy suffix slots.
    Raises ``LineageError`` when all 26 slots are taken.
    """
    if not is_valid_id(parent):
        raise LineageError(f"Invalid parent id: {parent!r}")
    existing = set(existing_ids)
    used = set()
    for cid in existing:
        if (
            cid != parent
            and cid.startswith(parent)
            and len(cid) == len(parent) + 1
            and cid[len(parent):] in CHILD_ALPHABET
        ):
            used.add(cid[len(parent):])
    for ch in CHILD_ALPHABET:
        candidate = parent + ch
        if ch not in used and candidate not in existing:
            return candidate
    raise LineageError(f"Cannot attach under {parent}: all 26 child slots (a-z) taken")
