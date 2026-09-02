"""lineage log — record metrics on an experiment."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .. import storage
from ._ui import bold, fail, info

_NUMERIC_RE = re.compile(r"^-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?$")


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "log",
        help="record metrics on an experiment.",
        description=(
            "Record one or more key=value metrics on an experiment. Values must "
            "be numeric (int or float). Existing keys are overwritten."
        ),
    )
    p.add_argument("exp_id", help="experiment id")
    p.add_argument(
        "metrics",
        nargs="*",
        help="metrics as key=value (e.g. -- loss=2.91 acc=0.81)",
    )
    p.set_defaults(_func=run)


def run(args, root: Path | None = None) -> int:
    base = Path(root) if root is not None else Path.cwd()
    if not storage.is_initialized(base):
        fail("Not a lineage repository (no .lineage/).")
    exp_id = args.exp_id
    if not storage.exists(exp_id, base):
        fail(f"Experiment not found: {exp_id}")

    metrics = _parse_metrics(getattr(args, "metrics", []) or [])
    if not metrics:
        fail("No metrics provided. Usage: lineage log <id> key=value [key=value ...]")

    meta = storage.load(exp_id, base)
    meta.metrics.update(metrics)
    storage.save(meta, base)
    info(f"logged on {bold(exp_id)}: " + ", ".join(f"{k}={v}" for k, v in metrics.items()))
    return 0


def _parse_metrics(items: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for item in items:
        if "=" not in item:
            fail(f"bad metric (expected key=value): {item}")
        key, _, val = item.partition("=")
        key = key.strip()
        val = val.strip()
        if not key:
            fail(f"empty key in metric: {item}")
        if not _NUMERIC_RE.match(val):
            fail(f"metric value must be numeric: {item}")
        out[key] = float(val)
    return out
