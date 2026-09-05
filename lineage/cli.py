"""Top-level CLI: argument parsing, subcommand dispatch, error handling."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .commands import add, diff_cmd, init, log, note, remove, revert, web
from .commands._ui import run_command

# Commands implemented in v0.1.
COMMANDS = {
    "add": add,
    "diff": diff_cmd,
    "revert": revert,
    "remove": remove,
    "note": note,
    "log": log,
    "web": web,
    "init": init,
}


def _register_add(subparsers) -> None:
    """`lineage add` has no add_parser; register a simple subparser inline."""
    p = subparsers.add_parser(
        "add",
        help="create an experiment from the current workspace.",
        description=(
            "Snapshot the current workspace as a new floating baseline "
            "(bN). Pass --from to attach under a parent instead "
            "(path-encoded id like b0a, diff vs the parent)."
        ),
    )
    p.add_argument("-m", "--message", default="", help="commit-style message for the experiment")
    p.add_argument(
        "--from",
        dest="from_",
        default=None,
        help="attach under this parent id instead of floating",
    )
    p.add_argument(
        "--snapshot",
        action="store_true",
        help="store a full snapshot (new baseline) instead of a diff",
    )
    p.add_argument(
        "--detached",
        action="store_true",
        help="create floating (this is the default; cannot combine with --from)",
    )
    p.set_defaults(_func=add.run)


# `add` registers itself; other modules expose add_parser.
_COMMAND_REGISTRARS = [_register_add]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lineage",
        description=(
            "Track the lineage of your experiments as a graph of snapshots and diffs. "
            "See Lineage.md for the full design."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"lineage {__version__}"
    )
    parser.add_argument(
        "-C",
        "--directory",
        default=None,
        help="operate on this directory instead of the current one",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    subparsers.required = True

    for name, mod in COMMANDS.items():
        if hasattr(mod, "add_parser"):
            mod.add_parser(subparsers)

    # Hand-rolled registrars (e.g. add).
    for registrar in _COMMAND_REGISTRARS:
        registrar(subparsers)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.directory).resolve() if args.directory else None
    handler = COMMANDS[args.command].run
    return run_command(lambda: handler(args, root))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
