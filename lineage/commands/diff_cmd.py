"""lineage diff — show a unified diff between two experiments (or vs parent)."""

from __future__ import annotations

import argparse
import difflib
from pathlib import Path

from .. import diff as diffmod
from .. import reconstruct, storage
from ..errors import LineageError
from ._ui import error, fail


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "diff",
        help="show diff between two experiments (or vs parent).",
        description=(
            "Show the unified diff between two experiments. If only one id is "
            "given, diff against the experiment's parent."
        ),
    )
    p.add_argument("a", help="first experiment id")
    p.add_argument("b", nargs="?", help="second experiment id (optional)")
    p.add_argument(
        "--stat", action="store_true", help="print only file-level change stats"
    )
    p.add_argument(
        "--files", action="store_true", help="print only the list of changed files"
    )
    p.set_defaults(_func=run)


def run(args, root: Path | None = None) -> int:
    base = Path(root) if root is not None else Path.cwd()
    if not storage.is_initialized(base):
        fail("Not a lineage repository (no .lineage/). Run `lineage add` first.")

    a_id = args.a
    if not storage.exists(a_id, base):
        fail(f"Experiment not found: {a_id}")

    b_id = args.b
    if b_id is None:
        meta = storage.load(a_id, base)
        b_id = meta.parent
        if b_id == a_id:
            fail("Root experiment has no parent to diff against.")

    if not storage.exists(b_id, base):
        fail(f"Experiment not found: {b_id}")

    try:
        fa = reconstruct.reconstruct_files(a_id, base)
        fb = reconstruct.reconstruct_files(b_id, base)
    except LineageError as e:
        fail(str(e))

    if args.files:
        _print_files(fa, fb)
        return 0
    if args.stat:
        _print_stat(fa, fb)
        return 0

    text = diffmod.make_unified_diff(fb, fa, old_label=f"a/{b_id}", new_label=f"b/{a_id}")
    if not text:
        print(f"(no changes between {b_id} and {a_id})")
        return 0
    print(text, end="" if text.endswith("\n") else "\n")
    return 0


def _print_files(fa: dict[str, bytes], fb: dict[str, bytes]) -> None:
    only_a = sorted(set(fa) - set(fb))
    only_b = sorted(set(fb) - set(fa))
    common = sorted(set(fa) & set(fb))
    for p in only_a:
        print(f"+ {p}")
    for p in only_b:
        print(f"- {p}")
    for p in common:
        if fa[p] != fb[p]:
            print(f"~ {p}")


def _print_stat(fa: dict[str, bytes], fb: dict[str, bytes]) -> None:
    only_a = sorted(set(fa) - set(fb))
    only_b = sorted(set(fb) - set(fa))
    common = sorted(set(fa) & set(fb))
    changed = [p for p in common if fa[p] != fb[p]]
    print(f"  added:    {len(only_a)}")
    print(f"  removed:  {len(only_b)}")
    print(f"  modified: {len(changed)}")
    for p in only_a:
        print(f"  + {p}")
    for p in only_b:
        print(f"  - {p}")
    for p in changed:
        print(f"  ~ {p}")
