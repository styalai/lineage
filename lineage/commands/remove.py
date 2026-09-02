"""lineage remove — delete an experiment."""

from __future__ import annotations

import argparse
from pathlib import Path

from .. import storage
from ..errors import HasChildrenError
from ._ui import bold, fail, success, warn


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "remove",
        help="delete an experiment.",
        description=(
            "Delete an experiment's directory. By default refuses if the "
            "experiment has children; pass --recursive to delete them too."
        ),
    )
    p.add_argument("exp_id", help="experiment id to remove")
    p.add_argument(
        "--recursive",
        action="store_true",
        help="also remove all descendants",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="do not prompt for confirmation (no prompt is shown today; reserved)",
    )
    p.set_defaults(_func=run)


def run(args, root: Path | None = None) -> int:
    base = Path(root) if root is not None else Path.cwd()
    if not storage.is_initialized(base):
        fail("Not a lineage repository (no .lineage/).")
    exp_id = args.exp_id
    if not storage.exists(exp_id, base):
        fail(f"Experiment not found: {exp_id}")

    children = storage.children_of(exp_id, base)
    if children and not args.recursive:
        raise HasChildrenError(exp_id, len(children))

    if args.recursive:
        # Recursively remove leaves first, then the node itself.
        _remove_recursive(exp_id, base)
    else:
        storage.remove_experiment(exp_id, base)

    success(f"removed {bold(exp_id)}" + (" and its descendants" if args.recursive else ""))
    return 0


def _remove_recursive(exp_id: str, base: Path) -> None:
    for child in storage.children_of(exp_id, base):
        _remove_recursive(child, base)
    storage.remove_experiment(exp_id, base)
