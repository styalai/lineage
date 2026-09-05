"""lineage init — stamp agent instruction files into a project."""

from __future__ import annotations

from pathlib import Path

from ..errors import LineageError
from ._ui import bold, fail, success

# Agent tool -> instruction filename it reads at the repo root.
# (opencode and codex both read AGENTS.md, so they share one file.)
TARGETS = {
    "opencode": "AGENTS.md",
    "claude": "CLAUDE.md",
    "codex": "AGENTS.md",
}


def template_text() -> str:
    """Load the instruction text from the AGENTS.md shipped with lineage."""
    candidate = Path(__file__).resolve().parent.parent / "AGENTS.md"
    if not candidate.is_file():
        raise LineageError(
            "instruction template not found: expected lineage/AGENTS.md "
            "inside the installed lineage package"
        )
    return candidate.read_text(encoding="utf-8")


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "init",
        help="write agent instruction files (AGENTS.md / CLAUDE.md).",
        description=(
            "Write the lineage usage instructions into this project's "
            "agent instruction files so coding agents checkpoint their "
            "experiments. Never overwrites an existing file unless --force."
        ),
    )
    p.add_argument(
        "--for",
        dest="for_",
        choices=["opencode", "claude", "codex", "all"],
        required=True,
        help="which agent tool to write instructions for",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing instruction files",
    )
    p.set_defaults(_func=run)


def run(args, root: Path | None = None) -> int:
    base = Path(root) if root is not None else Path.cwd()
    which = getattr(args, "for_", None)
    if which is None:
        raise LineageError("--for is required: opencode, claude, codex, or all")
    tools = list(TARGETS) if which == "all" else [which]
    names = sorted({TARGETS[t] for t in tools})
    force = bool(getattr(args, "force", False))

    text = template_text()
    refused: list[str] = []
    for name in names:
        dest = base / name
        if dest.exists():
            try:
                current = dest.read_text(encoding="utf-8")
            except OSError:
                current = None
            if current == text:
                success(f"{bold(name)} already up to date")
                continue
            if not force:
                refused.append(name)
                continue
            dest.write_text(text, encoding="utf-8")
            success(f"overwrote {bold(name)}")
        else:
            dest.write_text(text, encoding="utf-8")
            success(f"wrote {bold(name)}")
    if refused:
        fail(f"already exists (use --force to overwrite): {', '.join(refused)}")
    return 0
