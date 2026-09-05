"""HTTP server backend for ``lineage web``.

Hosts a small JSON API and a single-file HTML/JS frontend. Uses only the
stdlib so the installer doesn't need a build step.
"""

from __future__ import annotations

import json
import mimetypes
import re
import shutil
import socket
import threading
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlsplit

from . import diff, ids, reconstruct, snapshot, storage
from .commands import add as add_cmd
from .commands import log as log_cmd
from .errors import LineageError

# Default port; 0 = pick a free port.
DEFAULT_PORT = 5173

# Directory holding the static frontend shipped with the package.
STATIC_DIR = Path(__file__).resolve().parent / "static"


# ---------------------------------------------------------------------------
# Layout derivation
# ---------------------------------------------------------------------------


def depth_of(exp_id: str, meta_by_id: dict[str, storage.Meta]) -> int:
    """Return the depth of ``exp_id`` by walking meta parents to a root.

    Roots (``b0``, self-parented detached nodes, missing parents) are depth 0.
    Cycle-guarded: a loop terminates the walk instead of hanging.
    """
    depth = 0
    cur = exp_id
    seen = {cur}
    while True:
        m = meta_by_id.get(cur)
        if m is None or m.parent == cur or cur == ids.ROOT:
            return depth
        cur = m.parent
        if cur in seen:
            return depth
        seen.add(cur)
        depth += 1


def build_graph(root: Path) -> dict:
    """Build the graph payload sent to the frontend.

    Nodes are derived from ``storage.list_ids`` and enriched with metadata.
    Edges connect each non-root node to its parent.
    """
    nodes: list[dict] = []
    edges: list[dict] = []

    # Index by id for quick lookups.
    all_ids = storage.list_ids(root)
    meta_by_id: dict[str, storage.Meta] = {}
    for cid in all_ids:
        try:
            meta_by_id[cid] = storage.load(cid, root)
        except storage.LineageError:
            continue

    children_index: dict[str, list[str]] = {}
    for cid, m in meta_by_id.items():
        children_index.setdefault(m.parent, []).append(cid)

    # Depth per node (meta-parent walk), then x = index within the depth row
    # so nodes sharing a row never overlap. Both deterministic.
    depth_by_id = {cid: depth_of(cid, meta_by_id) for cid in meta_by_id}
    rows: dict[int, list[str]] = {}
    for cid in sorted(meta_by_id, key=ids.sort_key):
        rows.setdefault(depth_by_id[cid], []).append(cid)
    x_by_id = {cid: i for ids_in_row in rows.values() for i, cid in enumerate(ids_in_row)}

    for cid, m in meta_by_id.items():
        pos = {"x": x_by_id[cid], "depth": depth_by_id[cid]}
        # Sibling index = position among parent's children, sorted by id.
        siblings = sorted(children_index.get(m.parent, []), key=ids.sort_key)
        try:
            sibling_index = siblings.index(cid)
        except ValueError:
            sibling_index = 0
        nodes.append(
            {
                "id": cid,
                "parent": m.parent,
                "type": m.type,
                "message": m.message,
                "created_at": m.created_at,
                "metrics": m.metrics,
                "tags": m.tags,
                "position": pos,
                "sibling_index": sibling_index,
                "sibling_count": len(siblings),
            }
        )
        if cid != ids.ROOT and m.parent in meta_by_id and m.parent != cid:
            edges.append({"from": m.parent, "to": cid})

    return {
        "root": ids.ROOT,
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Diff / file payload helpers
# ---------------------------------------------------------------------------


def file_payload(exp_id: str, root: Path) -> dict:
    """Return the full file map of ``exp_id`` (reconstructed)."""
    files = reconstruct.reconstruct_files(exp_id, root)
    return {
        "id": exp_id,
        "files": {p: _b64_ifneeded(data) for p, data in files.items()},
        "file_count": len(files),
    }


def _b64_ifneeded(data: bytes) -> str:
    """Return text decoded as UTF-8 when possible, else as base64."""
    import base64

    try:
        return "text:" + data.decode("utf-8")
    except UnicodeDecodeError:
        return "bin:" + base64.b64encode(data).decode("ascii")


def _from_payload(data: str) -> bytes:
    """Inverse of ``_b64_ifneeded``."""
    import base64

    if data.startswith("text:"):
        return data[5:].encode("utf-8")
    if data.startswith("bin:"):
        return base64.b64decode(data[4:])
    raise ValueError(f"unknown payload prefix: {data!r}")


def diff_payload(a: str, b: str, root: Path) -> dict:
    """Return the unified diff and file-level stats between two experiments."""
    fa = reconstruct.reconstruct_files(a, root)
    fb = reconstruct.reconstruct_files(b, root)
    patch = diff.make_unified_diff(fa, fb, old_label=f"a/{a}", new_label=f"b/{b}")

    only_in_b = sorted(set(fb) - set(fa))
    only_in_a = sorted(set(fa) - set(fb))
    common = sorted(set(fa) & set(fb))
    modified = [p for p in common if fa[p] != fb[p]]

    return {
        "from": a,
        "to": b,
        "patch": patch,
        "stats": {
            "added": len(only_in_b),
            "removed": len(only_in_a),
            "modified": len(modified),
        },
        "files": {
            "added": only_in_b,
            "removed": only_in_a,
            "modified": modified,
        },
    }


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


@dataclass
class _State:
    root: Path
    frontend_metric: str = ""  # legacy single-slot; "" = show no metric in node header
    frontend_metric_a: str = ""  # first (primary) metric shown on each node
    frontend_metric_b: str = ""  # second (secondary) metric; "" = hidden


class LineageHTTPHandler(BaseHTTPRequestHandler):
    """One HTTP handler per request. State is stashed on the server."""

    server_version = "lineage-serve/0.1"

    # Quiet the default access log; we keep it on stderr for debugging.
    def log_message(self, format: str, *args) -> None:  # type: ignore[override]
        return

    # ----- helpers -----

    def _state(self) -> _State:
        return self.server.state  # type: ignore[attr-defined]

    def _root(self) -> Path:
        return self._state().root

    def _send_json(self, status: int, payload) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str | None = None) -> None:
        if not path.is_file():
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        body = path.read_bytes()
        ct = content_type or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body: bytes, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ----- dispatch -----

    def _read_json_body(self):
        """Return the parsed JSON body, or None when it is not valid JSON."""
        length = int(self.headers.get("Content-Length", "0") or "0")
        try:
            raw = self.rfile.read(length) if length > 0 else b"{}"
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _mutation_ids(self, *tokens: str) -> str | None:
        """Validate id tokens for a mutation; return an error string or None."""
        for tok in tokens:
            if not ids.is_valid_id(tok):
                return f"bad id: {tok!r}"
            if not storage.exists(tok, self._root()):
                return f"experiment not found: {tok!r}"
        return None

    def _api_add(self, payload: dict) -> None:
        message = str(payload.get("message", "") or "")
        parent = payload.get("parent") or None
        snapshot = bool(payload.get("snapshot", False))
        detached = bool(payload.get("detached", False))
        if parent is not None and not detached:
            err = self._mutation_ids(parent)
            if err:
                status = HTTPStatus.NOT_FOUND if "not found" in err else HTTPStatus.BAD_REQUEST
                self._send_json(status, {"error": err})
                return
        root = self._root()
        before = set(storage.list_ids(root))
        try:
            add_cmd.run(
                SimpleNamespace(message=message, from_=parent, snapshot=snapshot, detached=detached),
                root,
            )
        except SystemExit:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "add failed"})
            return
        except LineageError as e:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
            return
        created = sorted(set(storage.list_ids(root)) - before)
        if len(created) != 1:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "add did not create exactly one experiment"},
            )
            return
        self._send_json(HTTPStatus.OK, {"ok": True, "id": created[0]})

    def _api_log(self, payload: dict) -> None:
        exp_id = str(payload.get("id", "") or "")
        err = self._mutation_ids(exp_id)
        if err:
            status = HTTPStatus.NOT_FOUND if "not found" in err else HTTPStatus.BAD_REQUEST
            self._send_json(status, {"error": err})
            return
        metrics = payload.get("metrics", {})
        if not isinstance(metrics, dict) or not metrics:
            self._send_json(
                HTTPStatus.BAD_REQUEST, {"error": "metrics must be a non-empty object"}
            )
            return
        items: list[str] = []
        for key, value in metrics.items():
            key = str(key)
            if not log_cmd._KEY_RE.match(key):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": f"invalid metric key {key!r}"},
                )
                return
            items.append(f"{key}={value}")
        try:
            log_cmd.run(SimpleNamespace(exp_id=exp_id, metrics=items), self._root())
        except SystemExit:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "log failed"})
            return
        except LineageError as e:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
            return
        self._send_json(HTTPStatus.OK, {"ok": True, "id": exp_id})

    def _api_remove(self, payload: dict) -> None:
        exp_id = str(payload.get("id", "") or "")
        err = self._mutation_ids(exp_id)
        if err:
            status = HTTPStatus.NOT_FOUND if "not found" in err else HTTPStatus.BAD_REQUEST
            self._send_json(status, {"error": err})
            return
        root = self._root()
        children = sorted(storage.children_of(exp_id, root), key=ids.sort_key)
        recursive = bool(payload.get("recursive", False))
        if children and not recursive:
            self._send_json(
                HTTPStatus.CONFLICT,
                {"error": f"experiment has {len(children)} child(ren)", "children": children},
            )
            return
        # Closure over the meta-parent child relation, so reparented
        # subtrees are removed together with their parent.
        doomed = {exp_id}
        frontier = [exp_id]
        while frontier:
            cur = frontier.pop()
            for kid in storage.children_of(cur, root):
                if kid not in doomed:
                    doomed.add(kid)
                    frontier.append(kid)
        try:
            for cid in sorted(doomed):
                storage.remove_experiment(cid, root)
        except LineageError as e:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
            return
        self._send_json(HTTPStatus.OK, {"ok": True, "id": exp_id, "removed": sorted(doomed)})

    def _api_unconnect(self, payload: dict) -> None:
        """Detach an experiment from its parent (drop the incoming edge).

        Snapshot nodes are already self-contained. Diff nodes are
        materialized into standalone snapshots first (their patch was
        recorded against the old parent, so it cannot travel with them).
        Detached nodes get a self-parent, which draws no edge.
        """
        cid = str(payload.get("id", "") or "")
        err = self._mutation_ids(cid)
        if err:
            status = HTTPStatus.NOT_FOUND if "not found" in err else HTTPStatus.BAD_REQUEST
            self._send_json(status, {"error": err})
            return
        if cid == ids.ROOT:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "root has no parent to detach from"})
            return
        root = self._root()
        try:
            meta = storage.load(cid, root)
        except LineageError as e:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
            return
        if meta.parent == cid:
            self._send_json(HTTPStatus.OK, {"ok": True, "id": cid, "converted": False})
            return
        converted = False
        if meta.type == "diff":
            try:
                files = reconstruct.reconstruct_files(cid, root)
            except LineageError as e:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
                return
            snap_dir = storage.snapshot_dir(cid, root)
            snap_dir.mkdir(parents=True, exist_ok=True)
            for stale in snap_dir.iterdir():
                if stale.is_dir() and not stale.is_symlink():
                    shutil.rmtree(stale)
                else:
                    stale.unlink()
            for rel, data in files.items():
                target = snap_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            try:
                storage.diff_path(cid, root).unlink()
            except OSError:
                pass
            meta.type = "snapshot"
            converted = True
        # Detaching renames to a fresh floating bN id (subtree follows), so
        # the id keeps reflecting the position. Materialization above runs
        # first so the moved node is self-contained.
        try:
            storage.save(meta, root)
        except LineageError as e:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
            return
        new_id = ids.next_experiment_id(storage.list_ids(root))
        try:
            storage.rename_subtree(cid, new_id, new_id, root)
        except LineageError as e:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
            return
        self._send_json(HTTPStatus.OK, {"ok": True, "id": new_id, "converted": converted})

    def _api_connect(self, payload: dict) -> None:
        cid = str(payload.get("id", "") or "")
        parent = str(payload.get("parent", "") or "")
        err = self._mutation_ids(cid, parent)
        if err:
            status = HTTPStatus.NOT_FOUND if "not found" in err else HTTPStatus.BAD_REQUEST
            self._send_json(status, {"error": err})
            return
        if cid == ids.ROOT:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "cannot reparent the root"})
            return
        if parent == cid:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "cannot parent an experiment to itself"})
            return
        root = self._root()
        # Cycle check: walk the new parent's chain; it must not pass through cid.
        try:
            walker = parent
            for _ in range(len(storage.list_ids(root)) + 8):
                if walker == cid:
                    self._send_json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": f"connecting {cid} under {parent} would create a cycle"},
                    )
                    return
                wmeta = storage.load(walker, root)
                if wmeta.parent == walker or walker == ids.ROOT:
                    break
                walker = wmeta.parent
            meta = storage.load(cid, root)
        except LineageError as e:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
            return
        old_parent = meta.parent
        if old_parent == parent:
            # Already attached here: true no-op (ids already reflect position).
            self._send_json(HTTPStatus.OK, {"ok": True, "id": cid, "parent": parent})
            return
        # Attaching renames the node (plus its subtree) to a path id under
        # the new parent, so the id always reflects the current position.
        try:
            new_id = ids.next_child_id(parent, storage.list_ids(root))
            storage.rename_subtree(cid, new_id, parent, root)
            meta = storage.load(new_id, root)
        except LineageError as e:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
            return
        # Attached nodes don't need a full snapshot anymore: collapse to a
        # diff against the new parent. Only when the round-trip verifies
        # byte-identical (binary files can't diff) — otherwise keep the
        # snapshot so descendants keep reconstructing.
        converted = False
        snap_dir = storage.snapshot_dir(new_id, root)
        if meta.type == "snapshot" and snap_dir.is_dir():
            try:
                node_files = snapshot.list_snapshot_files(snap_dir)
                parent_files = reconstruct.reconstruct_files(parent, root)
                patch = diff.make_unified_diff(parent_files, node_files)
                check = diff.FileState(files=dict(parent_files))
                diff.apply_patch_text(check, patch, reverse=False)
                roundtrips = check.files == node_files
            except (OSError, LineageError):
                # Binary hunks (and any other unrepresentable content) fail
                # here: keep the snapshot.
                roundtrips = False
            if roundtrips:
                storage.write_text_atomic(storage.diff_path(new_id, root), patch)
                shutil.rmtree(snap_dir)
                meta.type = "diff"
                try:
                    storage.save(meta, root)
                except LineageError as e:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
                    return
                converted = True
        warning = None
        # Freshly converted diffs are recorded against the new parent, so
        # only pre-existing diffs moved across parents warn.
        if meta.type == "diff" and not converted:
            warning = (
                f"patch was recorded against {old_parent}; "
                f"contents now reconstruct against {parent}"
            )
        resp: dict = {"ok": True, "id": new_id, "parent": parent}
        if converted:
            resp["converted"] = True
        if warning:
            resp["warning"] = warning
        self._send_json(HTTPStatus.OK, resp)

    def do_GET(self) -> None:  # type: ignore[override]
        path = urlsplit(self.path).path
        qs = parse_qs(urlsplit(self.path).query)

        if path == "/" or path == "/index.html":
            self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return
        if path == "/api/graph":
            self._send_json(HTTPStatus.OK, build_graph(self._root()))
            return
        if path == "/api/meta":
            self._send_json(
                HTTPStatus.OK,
                {
                    "root": ids.ROOT,
                    "frontend_metric": self._state().frontend_metric,
                    "frontend_metric_a": self._state().frontend_metric_a,
                    "frontend_metric_b": self._state().frontend_metric_b,
                    "has_repo": storage.is_initialized(self._root()),
                },
            )
            return
        if path == "/api/files":
            exp_id = qs.get("id", [""])[0]
            if not ids.is_valid_id(exp_id) or not storage.exists(exp_id, self._root()):
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "experiment not found"})
                return
            self._send_json(HTTPStatus.OK, file_payload(exp_id, self._root()))
            return
        if path == "/api/diff":
            a = qs.get("from", [""])[0]
            b = qs.get("to", [""])[0]
            if not (ids.is_valid_id(a) and ids.is_valid_id(b)):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "bad id"})
                return
            if not (storage.exists(a, self._root()) and storage.exists(b, self._root())):
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "experiment not found"})
                return
            self._send_json(HTTPStatus.OK, diff_payload(a, b, self._root()))
            return
        if path == "/api/notes":
            exp_id = qs.get("id", [""])[0]
            if not ids.is_valid_id(exp_id) or not storage.exists(exp_id, self._root()):
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "experiment not found"})
                return
            self._send_json(
                HTTPStatus.OK,
                {"id": exp_id, "notes": storage.read_notes(exp_id, self._root())},
            )
            return

        # Static asset fallback (e.g. /static/app.js if we add any).
        if path.startswith("/static/"):
            rel = path[len("/static/") :]
            safe = (STATIC_DIR / rel).resolve()
            if not str(safe).startswith(str(STATIC_DIR.resolve())):
                self._send_json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
                return
            self._send_file(safe)
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # type: ignore[override]
        path = urlsplit(self.path).path
        if path == "/api/setting":
            length = int(self.headers.get("Content-Length", "0") or "0")
            try:
                raw = self.rfile.read(length) if length > 0 else b"{}"
                payload = json.loads(raw.decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid json"})
                return
            if "frontend_metric" in payload:
                self._state().frontend_metric = str(payload["frontend_metric"] or "")
            if "frontend_metric_a" in payload:
                self._state().frontend_metric_a = str(payload["frontend_metric_a"] or "")
            if "frontend_metric_b" in payload:
                self._state().frontend_metric_b = str(payload["frontend_metric_b"] or "")
            self._send_json(HTTPStatus.OK, {"ok": True})
            return
        if path == "/api/add":
            payload = self._read_json_body()
            if payload is None:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid json"})
                return
            self._api_add(payload)
            return
        if path == "/api/log":
            payload = self._read_json_body()
            if payload is None:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid json"})
                return
            self._api_log(payload)
            return
        if path == "/api/remove":
            payload = self._read_json_body()
            if payload is None:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid json"})
                return
            self._api_remove(payload)
            return
        if path == "/api/connect":
            payload = self._read_json_body()
            if payload is None:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid json"})
                return
            self._api_connect(payload)
            return
        if path == "/api/unconnect":
            payload = self._read_json_body()
            if payload is None:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid json"})
                return
            self._api_unconnect(payload)
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})


# ---------------------------------------------------------------------------
# Server factory + lifecycle
# ---------------------------------------------------------------------------


def _find_free_port(preferred: int) -> int:
    if preferred > 0:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", preferred))
                return preferred
            except OSError:
                pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LineageHTTPServer(ThreadingHTTPServer):
    """HTTP server that carries a ``state`` attribute and serves on 127.0.0.1."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler, state: _State) -> None:
        super().__init__(address, handler)
        self.state = state


def serve(
    root: Path,
    port: int = DEFAULT_PORT,
    host: str = "127.0.0.1",
    open_browser: bool = True,
    frontend_metric: str = "",
    frontend_metric_a: str = "",
    frontend_metric_b: str = "",
) -> tuple[LineageHTTPServer, int]:
    """Start the HTTP server on a free port. Returns (server, actual_port)."""
    if not storage.is_initialized(root):
        raise storage.LineageError(
            f"Not a lineage repository at {root}. Run `lineage add` first."
        )

    state = _State(
        root=root,
        frontend_metric=frontend_metric,
        frontend_metric_a=frontend_metric_a,
        frontend_metric_b=frontend_metric_b,
    )
    actual_port = _find_free_port(port)
    server = LineageHTTPServer((host, actual_port), LineageHTTPHandler, state)

    if open_browser:
        url = f"http://{host}:{actual_port}/"
        # Browsers are slow to start; don't block the server.
        threading.Thread(
            target=lambda: webbrowser.open(url), daemon=True
        ).start()
    return server, actual_port


def run_forever(server: LineageHTTPServer) -> None:
    """Block until interrupted."""
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
