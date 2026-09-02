"""lineage note — edit an experiment's notes."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .. import storage
from ._ui import bold, cyan, fail, info


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "note",
        help="edit an experiment's notes.",
        description=(
            "Open the experiment's notes in $VISUAL / $EDITOR. Pass --append to "
            "append to existing notes instead of replacing."
        ),
    )
    p.add_argument("exp_id", help="experiment id")
    p.add_argument(
        "--append",
        action="store_true",
        help="append instead of overwriting (you'll edit a temp file with the existing notes pre-loaded)",
    )
    p.add_argument(
        "-m",
        "--message",
        help="set the notes text non-interactively (replaces or appends based on --append)",
    )
    p.set_defaults(_func=run)


def run(args, root: Path | None = None) -> int:
    base = Path(root) if root is not None else Path.cwd()
    if not storage.is_initialized(base):
        fail("Not a lineage repository (no .lineage/).")
    exp_id = args.exp_id
    if not storage.exists(exp_id, base):
        fail(f"Experiment not found: {exp_id}")

    existing = storage.read_notes(exp_id, base)
    if getattr(args, "message", None) is not None:
        new = existing + ("\n" if existing and not existing.endswith("\n") else "") + args.message + "\n" if args.append else args.message + "\n"
        storage.write_notes(exp_id, new, base)
        info(f"updated notes for {bold(exp_id)}")
        return 0

    if not sys.stdin.isatty():
        # Non-interactive: read from stdin if anything is piped.
        if not sys.stdin.isatty():
            data = sys.stdin.read()
            if args.append and existing:
                data = existing + ("\n" if not existing.endswith("\n") else "") + data
            storage.write_notes(exp_id, data, base)
            info(f"updated notes for {bold(exp_id)}")
            return 0

    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or _default_editor()
    if not editor:
        fail("No editor configured. Set $VISUAL or $EDITOR, or use --message.")

    # Write a temp file with existing content pre-loaded; the editor edits it.
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".md",
        prefix=f"lineage-note-{exp_id}-",
        delete=False,
        encoding="utf-8",
    ) as tf:
        if existing:
            tf.write(existing)
            if not existing.endswith("\n"):
                tf.write("\n")
        tf_name = tf.name

    try:
        # Split editor command (supports "code -w" etc.).
        parts = editor.split()
        rc = subprocess.call(parts + [tf_name])
        if rc != 0:
            fail(f"editor exited with code {rc}")
        with open(tf_name, "r", encoding="utf-8") as fh:
            new_text = fh.read()
        storage.write_notes(exp_id, new_text, base)
        info(f"updated notes for {bold(exp_id)}")
        return 0
    finally:
        try:
            os.unlink(tf_name)
        except OSError:
            pass


def _default_editor() -> str | None:
    if sys.platform == "win32":
        return "notepad"
    for cand in ("nano", "vi"):
        # Cheap probe: check if it's on PATH.
        from shutil import which

        if which(cand):
            return cand
    return None
