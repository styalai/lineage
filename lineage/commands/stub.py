"""Stubs for commands listed in the spec but not yet implemented in v0.1."""

from __future__ import annotations

from pathlib import Path

from ..errors import NotImplemented
from ._ui import fail


def _stub(name: str):
    def run(args, root: Path | None = None) -> int:
        fail(
            f"`lineage {name}` is not implemented in v0.1. "
            f"See README.md for the current command set."
        )
        raise NotImplemented(name)  # unreachable; for type-checkers
    return run


# These wrappers are not registered with the CLI in v0.1; they exist so that
# future versions can simply switch the registration.
run_list = _stub("list")
run_show = _stub("show")
run_graph = _stub("graph")
run_gc = _stub("gc")
run_run = _stub("run")
