"""lineage log — record metrics on an experiment.

All metric values are stored as strings. Any key name is allowed, and values
may contain spaces if quoted (the parser strips surrounding quotes).
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from .. import storage
from ._ui import bold, fail, info


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "log",
        help="record metrics on an experiment.",
        description=(
            "Record one or more key=value metrics on an experiment. Any key "
            "name is allowed; values are stored as strings. Surround a value "
            "with single or double quotes to include spaces: name='alice b'."
        ),
    )
    p.add_argument("exp_id", help="experiment id")
    p.add_argument(
        "metrics",
        nargs="*",
        help="metrics as key=value (e.g. loss=2.91 dataset=imagenet best=true)",
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
        fail(
            "No metrics provided. "
            "Usage: lineage log <id> key=value [key=value ...]"
        )

    meta = storage.load(exp_id, base)
    meta.metrics.update(metrics)
    storage.save(meta, base)
    info(
        f"logged on {bold(exp_id)}: "
        + ", ".join(f"{k}={v}" for k, v in metrics.items())
    )
    return 0


_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-/]*$")


def _parse_metrics(items: list[str]) -> dict[str, str]:
    """Parse ``key=value`` items into ``{key: value}`` (values as strings).

    Accepted forms:
        key=value
        key="value with spaces"
        key='value with spaces'
    """
    out: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            fail(f"bad metric (expected key=value): {item!r}")
        key, _, val = item.partition("=")
        key = key.strip()
        val = val.strip()
        if not key:
            fail(f"empty key in metric: {item!r}")
        if not _KEY_RE.match(key):
            fail(
                f"invalid key {key!r}: must match [A-Za-z_][A-Za-z0-9_./-]*"
            )
        # Strip a single layer of matching surrounding quotes.
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        out[key] = val
    return out
