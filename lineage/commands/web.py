"""lineage web — launch a local web UI for the experiment graph."""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

from .. import serve as serve_mod
from .. import storage
from ._ui import bold, cyan, fail, info, success


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "web",
        help="launch a local web UI for the experiment graph.",
        description=(
            "Start a local HTTP server that visualises the experiment graph in "
            "your browser. Press Ctrl-C to stop."
        ),
    )
    p.add_argument(
        "--port",
        type=int,
        default=serve_mod.DEFAULT_PORT,
        help=f"port to bind (default: {serve_mod.DEFAULT_PORT}; 0 = pick a free port)",
    )
    p.add_argument(
        "--host",
        default="127.0.0.1",
        help="interface to bind (default: 127.0.0.1)",
    )
    p.add_argument(
        "--no-browser",
        action="store_true",
        help="do not auto-open the browser",
    )
    p.add_argument(
        "--metric",
        default="",
        help="metric to display on each node (legacy single-slot; can be changed in the UI)",
    )
    p.add_argument(
        "--metric-a",
        default="",
        help="primary metric shown on each node (overrides --metric for the first slot)",
    )
    p.add_argument(
        "--metric-b",
        default="",
        help="secondary metric shown on each node (optional)",
    )
    p.set_defaults(_func=run)


def run(args, root: Path | None = None) -> int:
    base = Path(root) if root is not None else Path.cwd()
    if not storage.is_initialized(base):
        fail("Not a lineage repository (no .lineage/). Run `lineage add` first.")

    metric_a = args.metric_a or args.metric
    metric_b = args.metric_b or ""

    server, actual_port = serve_mod.serve(
        root=base,
        port=args.port,
        host=args.host,
        open_browser=not args.no_browser,
        frontend_metric=args.metric or "",
        frontend_metric_a=metric_a,
        frontend_metric_b=metric_b,
    )
    url = f"http://{args.host}:{actual_port}/"
    success(f"lineage web running at {bold(url)}")
    info("press Ctrl-C to stop")

    # Run the server in a background thread so we can keep the foreground
    # free for status updates / signals.
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        info("shutting down…")
        server.shutdown()
        server.server_close()
        success("bye")
        return 0
