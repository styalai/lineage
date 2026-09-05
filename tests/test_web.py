"""Tests for the serve backend and the lineage web CLI subcommand."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request
from http.client import HTTPConnection
from pathlib import Path

import pytest

from lineage import serve, storage


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def _metas(pairs: list[tuple[str, str]]) -> dict[str, storage.Meta]:
    return {
        cid: storage.Meta(id=cid, parent=parent, type="snapshot")
        for cid, parent in pairs
    }


def test_depth_of_root_is_zero():
    assert serve.depth_of("b0", _metas([("b0", "b0")])) == 0


def test_depth_of_follows_meta_parents():
    metas = _metas([("b0", "b0"), ("b1", "b0"), ("b2", "b1"), ("b3", "b0")])
    assert serve.depth_of("b1", metas) == 1
    assert serve.depth_of("b2", metas) == 2
    assert serve.depth_of("b3", metas) == 1


def test_depth_of_detached_self_parent_is_zero():
    assert serve.depth_of("b1", _metas([("b1", "b1")])) == 0


def test_depth_of_cycle_terminates():
    metas = _metas([("b1", "b2"), ("b2", "b1")])
    assert serve.depth_of("b1", metas) == 1


def test_build_graph_positions_share_depth_rows(workdir: Path):
    # b3 (child of b1) sits one row below; b1/b2 share the depth-1 row.
    storage.save(storage.Meta(id="b0", parent="b0", type="snapshot"), workdir)
    storage.save(storage.Meta(id="b1", parent="b0", type="diff"), workdir)
    storage.save(storage.Meta(id="b2", parent="b0", type="diff"), workdir)
    storage.save(storage.Meta(id="b3", parent="b1", type="diff"), workdir)
    g = serve.build_graph(workdir)
    by_id = {n["id"]: n for n in g["nodes"]}
    assert by_id["b0"]["position"] == {"x": 0, "depth": 0}
    assert by_id["b1"]["position"] == {"x": 0, "depth": 1}
    assert by_id["b2"]["position"] == {"x": 1, "depth": 1}
    assert by_id["b3"]["position"] == {"x": 0, "depth": 2}


def test_build_graph_supports_legacy_prefix_ids(workdir: Path):
    # Workspaces created before sequential numbering still graph.
    storage.save(storage.Meta(id="b0", parent="b0", type="snapshot"), workdir)
    storage.save(storage.Meta(id="b1", parent="b0", type="diff"), workdir)
    g = serve.build_graph(workdir)
    by_id = {n["id"]: n for n in g["nodes"]}
    assert by_id["b1"]["position"] == {"x": 0, "depth": 1}
    assert {(e["from"], e["to"]) for e in g["edges"]} == {("b0", "b1")}


# ---------------------------------------------------------------------------
# build_graph
# ---------------------------------------------------------------------------


def test_build_graph_empty(workdir: Path):
    storage.ensure_initialized(workdir)
    g = serve.build_graph(workdir)
    assert g["root"] == "b0"
    assert g["nodes"] == []
    assert g["edges"] == []


def test_build_graph_three_experiments(workdir: Path):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    storage.save(
        storage.Meta(id="b0", parent="b0", type="snapshot", message="root"),
        workdir,
    )
    (workdir / "a.txt").write_text("v1\n", encoding="utf-8")
    storage.save(
        storage.Meta(id="b1", parent="b0", type="diff", message="v1"),
        workdir,
    )
    (workdir / "a.txt").write_text("v2\n", encoding="utf-8")
    storage.save(
        storage.Meta(id="b2", parent="b0", type="diff", message="v2", metrics={"loss": "1.2"}),
        workdir,
    )
    g = serve.build_graph(workdir)
    assert {n["id"] for n in g["nodes"]} == {"b0", "b1", "b2"}
    # Edges connect each non-root to its parent.
    assert {(e["from"], e["to"]) for e in g["edges"]} == {("b0", "b1"), ("b0", "b2")}
    # Positions come from meta-parent depth, x = index within the depth row.
    by_id = {n["id"]: n for n in g["nodes"]}
    assert by_id["b0"]["position"] == {"x": 0, "depth": 0}
    assert by_id["b1"]["position"] == {"x": 0, "depth": 1}
    assert by_id["b2"]["position"] == {"x": 1, "depth": 1}
    # Metrics are forwarded.
    assert by_id["b2"]["metrics"] == {"loss": "1.2"}


# ---------------------------------------------------------------------------
# HTTP server: end-to-end
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(root: Path) -> tuple[serve.LineageHTTPServer, int]:
    server, port = serve.serve(
        root=root,
        port=0,  # pick a free port
        host="127.0.0.1",
        open_browser=False,
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    # Give the server a tick to bind.
    time.sleep(0.05)
    return server, port


def _http_get(port: int, path: str, method: str = "GET", body: bytes | None = None, headers: dict | None = None) -> tuple[int, dict, bytes]:
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        h = {"Accept": "application/json"}
        if headers:
            h.update(headers)
        conn.request(method, path, body=body, headers=h)
        resp = conn.getresponse()
        data = resp.read()
        ctype = resp.getheader("Content-Type", "")
        return resp.status, dict(resp.getheaders()), data
    finally:
        conn.close()


def test_serve_init_raises_when_uninitialized(tmp_path: Path):
    with pytest.raises(storage.LineageError):
        serve.serve(root=tmp_path, port=0, host="127.0.0.1", open_browser=False)


def test_serve_serves_index(workdir: Path):
    storage.ensure_initialized(workdir)
    server, port = _start_server(workdir)
    try:
        status, hdrs, body = _http_get(port, "/")
        assert status == 200
        assert "text/html" in hdrs.get("Content-Type", "")
        assert b"lineage graph" in body
    finally:
        server.shutdown()
        server.server_close()


def test_serve_api_meta(workdir: Path):
    storage.ensure_initialized(workdir)
    server, port = _start_server(workdir)
    try:
        status, _, body = _http_get(port, "/api/meta")
        assert status == 200
        payload = json.loads(body)
        assert payload["root"] == "b0"
        assert payload["frontend_metric"] == ""
        # Two-metric slots default to empty.
        assert payload["frontend_metric_a"] == ""
        assert payload["frontend_metric_b"] == ""
    finally:
        server.shutdown()
        server.server_close()


def test_serve_api_graph(workdir: Path):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    storage.save(storage.Meta(id="b0", parent="b0", type="snapshot"), workdir)
    (workdir / "a.txt").write_text("v1\n", encoding="utf-8")
    storage.save(storage.Meta(id="b1", parent="b0", type="diff"), workdir)
    server, port = _start_server(workdir)
    try:
        status, _, body = _http_get(port, "/api/graph")
        assert status == 200
        g = json.loads(body)
        assert {n["id"] for n in g["nodes"]} == {"b0", "b1"}
        # position is in the node payload
        b1 = next(n for n in g["nodes"] if n["id"] == "b1")
        assert b1["position"] == {"x": 0, "depth": 1}
    finally:
        server.shutdown()
        server.server_close()


def test_serve_api_files(workdir: Path):
    (workdir / "a.txt").write_text("hello\n", encoding="utf-8")
    (workdir / "b.txt").write_text("world\n", encoding="utf-8")
    storage.save(storage.Meta(id="b0", parent="b0", type="snapshot"), workdir)
    # Reconstruct needs the actual snapshot/ directory on disk, not just the
    # meta.json. Easiest: write the file into the snapshot dir too.
    snap_dir = storage.snapshot_dir("b0", workdir)
    snap_dir.mkdir(parents=True, exist_ok=True)
    (snap_dir / "a.txt").write_text("hello\n", encoding="utf-8")
    (snap_dir / "b.txt").write_text("world\n", encoding="utf-8")
    server, port = _start_server(workdir)
    try:
        status, _, body = _http_get(port, "/api/files?id=b0")
        assert status == 200
        payload = json.loads(body)
        assert payload["id"] == "b0"
        assert payload["file_count"] == 2
        assert payload["files"]["a.txt"].startswith("text:")
        assert "hello" in payload["files"]["a.txt"]
    finally:
        server.shutdown()
        server.server_close()


def test_serve_api_files_unknown_returns_404(workdir: Path):
    storage.ensure_initialized(workdir)
    server, port = _start_server(workdir)
    try:
        status, _, _ = _http_get(port, "/api/files?id=b0zz")
        assert status == 404
    finally:
        server.shutdown()
        server.server_close()


def test_serve_api_diff(workdir: Path):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    storage.save(storage.Meta(id="b0", parent="b0", type="snapshot"), workdir)
    snap = storage.snapshot_dir("b0", workdir)
    snap.mkdir(parents=True, exist_ok=True)
    (snap / "a.txt").write_text("v0\n", encoding="utf-8")
    (workdir / "a.txt").write_text("v1\n", encoding="utf-8")
    storage.save(storage.Meta(id="b1", parent="b0", type="diff"), workdir)
    dp = storage.diff_path("b1", workdir)
    dp.write_text(
        "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-v0\n+v1\n",
        encoding="utf-8",
    )
    server, port = _start_server(workdir)
    try:
        status, _, body = _http_get(port, "/api/diff?from=b0&to=b1")
        assert status == 200
        d = json.loads(body)
        assert d["from"] == "b0"
        assert d["to"] == "b1"
        assert d["stats"]["modified"] == 1
        assert "-v0" in d["patch"]
        assert "+v1" in d["patch"]
    finally:
        server.shutdown()
        server.server_close()


def test_serve_api_diff_rejects_bad_id(workdir: Path):
    storage.ensure_initialized(workdir)
    server, port = _start_server(workdir)
    try:
        status, _, _ = _http_get(port, "/api/diff?from=evil&to=b0")
        assert status == 400
    finally:
        server.shutdown()
        server.server_close()


def test_serve_api_notes(workdir: Path):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    storage.save(storage.Meta(id="b0", parent="b0", type="snapshot"), workdir)
    storage.write_notes("b0", "# hello\nworld\n", workdir)
    server, port = _start_server(workdir)
    try:
        status, _, body = _http_get(port, "/api/notes?id=b0")
        assert status == 200
        payload = json.loads(body)
        assert payload["id"] == "b0"
        assert "hello" in payload["notes"]
    finally:
        server.shutdown()
        server.server_close()


def test_serve_post_setting(workdir: Path):
    storage.ensure_initialized(workdir)
    server, port = _start_server(workdir)
    try:
        body = json.dumps({"frontend_metric": "loss"}).encode("utf-8")
        status, _, _ = _http_get(
            port,
            "/api/setting",
            method="POST",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        assert status == 200
        # The setting is reflected in subsequent /api/meta calls.
        _, _, meta_body = _http_get(port, "/api/meta")
        meta = json.loads(meta_body)
        assert meta["frontend_metric"] == "loss"
    finally:
        server.shutdown()
        server.server_close()


def test_serve_post_setting_two_metrics(workdir: Path):
    storage.ensure_initialized(workdir)
    server, port = _start_server(workdir)
    try:
        body = json.dumps({"frontend_metric_a": "loss", "frontend_metric_b": "acc"}).encode("utf-8")
        status, _, _ = _http_get(
            port,
            "/api/setting",
            method="POST",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        assert status == 200
        _, _, meta_body = _http_get(port, "/api/meta")
        meta = json.loads(meta_body)
        assert meta["frontend_metric_a"] == "loss"
        assert meta["frontend_metric_b"] == "acc"
        # Setting only _a leaves _b empty.
        body = json.dumps({"frontend_metric_a": "f1"}).encode("utf-8")
        _http_get(port, "/api/setting", method="POST", body=body,
                  headers={"Content-Type": "application/json"})
        _, _, meta_body = _http_get(port, "/api/meta")
        meta = json.loads(meta_body)
        assert meta["frontend_metric_a"] == "f1"
        assert meta["frontend_metric_b"] == "acc"  # unchanged
    finally:
        server.shutdown()
        server.server_close()


def test_serve_static_path_traversal_blocked(workdir: Path):
    storage.ensure_initialized(workdir)
    server, port = _start_server(workdir)
    try:
        # urlopen-normalized: requesting /static/../etc/passwd should not leak
        # anything outside STATIC_DIR. The handler rejects any resolved path
        # that doesn't live under STATIC_DIR.
        # Using a raw socket to send the literal bytes so traversal isn't
        # normalized away by the client.
        import socket as _s
        s = _s.create_connection(("127.0.0.1", port), timeout=5)
        try:
            s.sendall(b"GET /static/../README.md HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
            data = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
        finally:
            s.close()
        assert b"200" not in data.split(b"\r\n", 1)[0], "traversal should not return 200"
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# Mutation API: add / log / remove / connect
# ---------------------------------------------------------------------------


def _post(port: int, path: str, payload: dict) -> tuple[int, dict]:
    status, _, body = _http_get(
        port,
        path,
        method="POST",
        body=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    return status, json.loads(body)


def _seed_pair(workdir: Path) -> None:
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    storage.save(
        storage.Meta(id="b0", parent="b0", type="snapshot", message="root"),
        workdir,
    )
    storage.save(
        storage.Meta(id="b1", parent="b0", type="diff", message="child"),
        workdir,
    )


def _graph_ids(port: int) -> tuple[set[str], list[dict]]:
    _, _, body = _http_get(port, "/api/graph")
    g = json.loads(body)
    return {n["id"] for n in g["nodes"]}, g["edges"]


def test_api_add_creates_child(workdir: Path):
    storage.ensure_initialized(workdir)
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    server, port = _start_server(workdir)
    try:
        status, payload = _post(port, "/api/add", {"message": "root"})
        assert status == 200, payload
        assert payload["id"] == "b0"
        (workdir / "a.txt").write_text("v1\n", encoding="utf-8")
        status, payload = _post(port, "/api/add", {"message": "tweak", "parent": "b0"})
        assert status == 200, payload
        # Attached under b0: path-encoded id.
        assert payload["id"] == "b0a"
        node_ids, _ = _graph_ids(port)
        assert node_ids == {"b0", "b0a"}
    finally:
        server.shutdown()
        server.server_close()


def test_api_add_bad_parent(workdir: Path):
    storage.ensure_initialized(workdir)
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    server, port = _start_server(workdir)
    try:
        status, payload = _post(port, "/api/add", {"message": "x", "parent": "b0z"})
        assert status == 404, payload
        assert "error" in payload
    finally:
        server.shutdown()
        server.server_close()


def test_api_log_sets_metrics(workdir: Path):
    _seed_pair(workdir)
    server, port = _start_server(workdir)
    try:
        status, payload = _post(
            port, "/api/log", {"id": "b1", "metrics": {"loss": "0.5", "acc": 0.9}}
        )
        assert status == 200, payload
        _, _, body = _http_get(port, "/api/graph")
        by_id = {n["id"]: n for n in json.loads(body)["nodes"]}
        assert by_id["b1"]["metrics"] == {"loss": "0.5", "acc": "0.9"}
    finally:
        server.shutdown()
        server.server_close()


def test_api_log_rejects(workdir: Path):
    _seed_pair(workdir)
    server, port = _start_server(workdir)
    try:
        status, payload = _post(port, "/api/log", {"id": "b0z", "metrics": {"loss": "1"}})
        assert status == 404, payload
        status, payload = _post(port, "/api/log", {"id": "b1", "metrics": {"9bad": "1"}})
        assert status == 400, payload
        status, payload = _post(port, "/api/log", {"id": "b1", "metrics": {}})
        assert status == 400, payload
    finally:
        server.shutdown()
        server.server_close()


def test_api_remove_leaf(workdir: Path):
    _seed_pair(workdir)
    server, port = _start_server(workdir)
    try:
        status, payload = _post(port, "/api/remove", {"id": "b1"})
        assert status == 200, payload
        assert payload["removed"] == ["b1"]
        node_ids, _ = _graph_ids(port)
        assert node_ids == {"b0"}
    finally:
        server.shutdown()
        server.server_close()


def test_api_remove_refuses_children_without_recursive(workdir: Path):
    _seed_pair(workdir)
    server, port = _start_server(workdir)
    try:
        status, payload = _post(port, "/api/remove", {"id": "b0"})
        assert status == 409, payload
        assert payload["children"] == ["b1"]
        node_ids, _ = _graph_ids(port)
        assert node_ids == {"b0", "b1"}
    finally:
        server.shutdown()
        server.server_close()


def test_api_remove_recursive(workdir: Path):
    _seed_pair(workdir)
    server, port = _start_server(workdir)
    try:
        status, payload = _post(port, "/api/remove", {"id": "b0", "recursive": True})
        assert status == 200, payload
        assert sorted(payload["removed"]) == ["b0", "b1"]
        node_ids, _ = _graph_ids(port)
        assert node_ids == set()
    finally:
        server.shutdown()
        server.server_close()


def test_api_remove_unknown(workdir: Path):
    _seed_pair(workdir)
    server, port = _start_server(workdir)
    try:
        status, payload = _post(port, "/api/remove", {"id": "b0z"})
        assert status == 404, payload
    finally:
        server.shutdown()
        server.server_close()


def test_api_connect_reparents(workdir: Path):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    storage.save(
        storage.Meta(id="b0", parent="b0", type="snapshot", message="root"),
        workdir,
    )
    storage.save(
        storage.Meta(id="b1", parent="b0", type="diff", message="a"),
        workdir,
    )
    storage.save(
        storage.Meta(id="b2", parent="b0", type="snapshot", message="b"),
        workdir,
    )
    server, port = _start_server(workdir)
    try:
        status, payload = _post(port, "/api/connect", {"id": "b1", "parent": "b2"})
        assert status == 200, payload
        # Attaching renames to a path id under the new parent.
        assert payload["id"] == "b2a"
        assert payload["parent"] == "b2"
        # b1 is a diff reparented away from its patch parent: warn.
        assert "warning" in payload
        node_ids, edges = _graph_ids(port)
        assert node_ids == {"b0", "b2", "b2a"}
        assert {"from": "b2", "to": "b2a"} in edges
        assert {"from": "b0", "to": "b1"} not in edges
    finally:
        server.shutdown()
        server.server_close()


def test_api_connect_rejects(workdir: Path):
    _seed_pair(workdir)
    server, port = _start_server(workdir)
    try:
        # Unknown node.
        status, _ = _post(port, "/api/connect", {"id": "b0z", "parent": "b0"})
        assert status == 404
        # Root cannot be reparented.
        status, payload = _post(port, "/api/connect", {"id": "b0", "parent": "b1"})
        assert status == 400, payload
        # Self-parenting.
        status, _ = _post(port, "/api/connect", {"id": "b1", "parent": "b1"})
        assert status == 400
        # Cycle: b0 under its own child b1.
        status, payload = _post(port, "/api/connect", {"id": "b1", "parent": "b0"})
        assert status == 200, payload  # no-op reparent back, allowed
        status, payload = _post(port, "/api/connect", {"id": "b0", "parent": "b1"})
        assert status == 400, payload  # root rule fires first here
    finally:
        server.shutdown()
        server.server_close()


def test_api_connect_cycle_between_diffs(workdir: Path):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    storage.save(
        storage.Meta(id="b0", parent="b0", type="snapshot", message="root"),
        workdir,
    )
    storage.save(
        storage.Meta(id="b1", parent="b0", type="diff", message="a"),
        workdir,
    )
    storage.save(
        storage.Meta(id="b2", parent="b1", type="diff", message="aa"),
        workdir,
    )
    server, port = _start_server(workdir)
    try:
        status, payload = _post(
            port, "/api/connect", {"id": "b1", "parent": "b2"}
        )
        assert status == 400, payload
        assert "cycle" in payload["error"]
    finally:
        server.shutdown()
        server.server_close()


def _seed_snapshot_with_files(workdir: Path) -> None:
    """A real b0 snapshot (files on disk) plus a b1 diff against it."""
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    storage.save(
        storage.Meta(id="b0", parent="b0", type="snapshot", message="root"),
        workdir,
    )
    snap_dir = storage.snapshot_dir("b0", workdir)
    snap_dir.mkdir(parents=True, exist_ok=True)
    (snap_dir / "a.txt").write_text("v0\n", encoding="utf-8")
    storage.save(
        storage.Meta(id="b1", parent="b0", type="diff", message="child"),
        workdir,
    )
    storage.write_text_atomic(
        storage.diff_path("b1", workdir),
        "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-v0\n+v1\n",
    )


def test_api_unconnect_diff_materializes_snapshot(workdir: Path):
    _seed_snapshot_with_files(workdir)
    server, port = _start_server(workdir)
    try:
        status, payload = _post(port, "/api/unconnect", {"id": "b1"})
        assert status == 200, payload
        assert payload["converted"] is True
        # Detaching renames to a fresh floating bN id.
        assert payload["id"] == "b2"
        # Edge gone, node retyped, content intact and self-contained.
        node_ids, edges = _graph_ids(port)
        assert node_ids == {"b0", "b2"}
        assert edges == []
        meta = storage.load("b2", workdir)
        assert meta.type == "snapshot" and meta.parent == "b2"
        assert (storage.snapshot_dir("b2", workdir) / "a.txt").read_text() == "v1\n"
        assert not storage.diff_path("b2", workdir).exists()
        from lineage import reconstruct

        assert reconstruct.reconstruct_files("b2", workdir) == {"a.txt": b"v1\n"}
    finally:
        server.shutdown()
        server.server_close()


def test_api_unconnect_snapshot_just_detaches(workdir: Path):
    _seed_snapshot_with_files(workdir)
    storage.save(
        storage.Meta(id="b2", parent="b0", type="snapshot", message="b"),
        workdir,
    )
    (storage.snapshot_dir("b2", workdir)).mkdir(parents=True, exist_ok=True)
    server, port = _start_server(workdir)
    try:
        status, payload = _post(port, "/api/unconnect", {"id": "b2"})
        assert status == 200, payload
        assert payload["converted"] is False
        # Renamed to a fresh floating id; the old edge is gone but b1's stays.
        assert payload["id"] == "b3"
        node_ids, edges = _graph_ids(port)
        assert node_ids == {"b0", "b1", "b3"}
        assert {"from": "b0", "to": "b3"} not in edges
        assert {"from": "b0", "to": "b1"} in edges
    finally:
        server.shutdown()
        server.server_close()


def test_api_unconnect_rejects(workdir: Path):
    _seed_pair(workdir)
    server, port = _start_server(workdir)
    try:
        status, _ = _post(port, "/api/unconnect", {"id": "b0z"})
        assert status == 404
        status, payload = _post(port, "/api/unconnect", {"id": "b0"})
        assert status == 400, payload
    finally:
        server.shutdown()
        server.server_close()


def test_api_add_snapshot_forces_baseline(workdir: Path):
    storage.ensure_initialized(workdir)
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    server, port = _start_server(workdir)
    try:
        status, payload = _post(port, "/api/add", {"message": "root"})
        assert status == 200, payload
        (workdir / "a.txt").write_text("v1\n", encoding="utf-8")
        status, payload = _post(
            port, "/api/add", {"message": "base", "parent": "b0", "snapshot": True}
        )
        assert status == 200, payload
        assert payload["id"] == "b0a"
        meta = storage.load("b0a", workdir)
        assert meta.type == "snapshot"
        assert (storage.snapshot_dir("b0a", workdir) / "a.txt").read_text() == "v1\n"
        from lineage import reconstruct

        files = reconstruct.reconstruct_files("b0a", workdir)
        assert files["a.txt"] == b"v1\n"
    finally:
        server.shutdown()
        server.server_close()


def test_api_add_detached_creates_floating_baseline(workdir: Path):
    storage.ensure_initialized(workdir)
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    server, port = _start_server(workdir)
    try:
        status, payload = _post(port, "/api/add", {"message": "root"})
        assert status == 200, payload
        (workdir / "a.txt").write_text("v1\n", encoding="utf-8")
        status, payload = _post(
            port, "/api/add", {"message": "float", "snapshot": True, "detached": True}
        )
        assert status == 200, payload
        assert payload["id"] == "b1"
        meta = storage.load("b1", workdir)
        assert meta.type == "snapshot" and meta.parent == "b1"
        # No edge to the new node.
        node_ids, edges = _graph_ids(port)
        assert node_ids == {"b0", "b1"}
        assert edges == []
    finally:
        server.shutdown()
        server.server_close()


def test_api_connect_renames_subtree(workdir: Path):
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    storage.save(
        storage.Meta(id="b0", parent="b0", type="snapshot", message="root"),
        workdir,
    )
    storage.save(
        storage.Meta(id="b1", parent="b0", type="snapshot", message="a"),
        workdir,
    )
    storage.save(
        storage.Meta(id="b2", parent="b1", type="snapshot", message="child"),
        workdir,
    )
    storage.save(
        storage.Meta(id="b3", parent="b0", type="snapshot", message="b"),
        workdir,
    )
    server, port = _start_server(workdir)
    try:
        status, payload = _post(port, "/api/connect", {"id": "b1", "parent": "b3"})
        assert status == 200, payload
        assert payload["id"] == "b3a"
        node_ids, edges = _graph_ids(port)
        assert node_ids == {"b0", "b3", "b3a", "b3aa"}
        assert {"from": "b3", "to": "b3a"} in edges
        assert {"from": "b3a", "to": "b3aa"} in edges
    finally:
        server.shutdown()
        server.server_close()


def _seed_two_snapshots(workdir: Path, b1_files: dict) -> None:
    """b0 snapshot {a.txt: v0} plus floating b1 snapshot with ``b1_files``."""
    (workdir / "a.txt").write_text("v0\n", encoding="utf-8")
    storage.save(
        storage.Meta(id="b0", parent="b0", type="snapshot", message="root"),
        workdir,
    )
    snap0 = storage.snapshot_dir("b0", workdir)
    snap0.mkdir(parents=True, exist_ok=True)
    (snap0 / "a.txt").write_text("v0\n", encoding="utf-8")
    storage.save(
        storage.Meta(id="b1", parent="b1", type="snapshot", message="float"),
        workdir,
    )
    snap1 = storage.snapshot_dir("b1", workdir)
    snap1.mkdir(parents=True, exist_ok=True)
    for rel, data in b1_files.items():
        (snap1 / rel).write_bytes(data)


def test_api_connect_converts_snapshot_to_diff(workdir: Path):
    _seed_two_snapshots(workdir, {"a.txt": b"v1\n"})
    server, port = _start_server(workdir)
    try:
        status, payload = _post(port, "/api/connect", {"id": "b1", "parent": "b0"})
        assert status == 200, payload
        assert payload["id"] == "b0a"
        assert payload.get("converted") is True
        # Fresh patch against the new parent: no stale-patch warning.
        assert "warning" not in payload
        meta = storage.load("b0a", workdir)
        assert meta.type == "diff" and meta.parent == "b0"
        assert not storage.snapshot_dir("b0a", workdir).exists()
        assert storage.diff_path("b0a", workdir).is_file()
        from lineage import reconstruct

        assert reconstruct.reconstruct_files("b0a", workdir) == {"a.txt": b"v1\n"}
        node_ids, edges = _graph_ids(port)
        assert node_ids == {"b0", "b0a"}
        assert {(e["from"], e["to"]) for e in edges} == {("b0", "b0a")}
    finally:
        server.shutdown()
        server.server_close()


def test_api_connect_keeps_snapshot_when_binary(workdir: Path):
    _seed_two_snapshots(workdir, {"a.txt": b"v0\n", "bin.dat": b"\xff\xfe\x00bin"})
    server, port = _start_server(workdir)
    try:
        status, payload = _post(port, "/api/connect", {"id": "b1", "parent": "b0"})
        assert status == 200, payload
        assert payload["id"] == "b0a"
        assert not payload.get("converted", False)
        meta = storage.load("b0a", workdir)
        assert meta.type == "snapshot"
        assert (storage.snapshot_dir("b0a", workdir) / "bin.dat").is_file()
        from lineage import reconstruct

        assert reconstruct.reconstruct_files("b0a", workdir) == {
            "a.txt": b"v0\n",
            "bin.dat": b"\xff\xfe\x00bin",
        }
    finally:
        server.shutdown()
        server.server_close()


def test_api_connect_conversion_keeps_descendants(workdir: Path):
    _seed_two_snapshots(workdir, {"a.txt": b"v1\n"})
    storage.save(
        storage.Meta(id="b2", parent="b1", type="diff", message="child"),
        workdir,
    )
    storage.write_text_atomic(
        storage.diff_path("b2", workdir),
        "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-v1\n+v2\n",
    )
    server, port = _start_server(workdir)
    try:
        status, payload = _post(port, "/api/connect", {"id": "b1", "parent": "b0"})
        assert status == 200, payload
        assert payload["id"] == "b0a"
        node_ids, edges = _graph_ids(port)
        assert node_ids == {"b0", "b0a", "b0aa"}
        assert {(e["from"], e["to"]) for e in edges} == {
            ("b0", "b0a"),
            ("b0a", "b0aa"),
        }
        from lineage import reconstruct

        assert reconstruct.reconstruct_files("b0aa", workdir) == {"a.txt": b"v2\n"}
    finally:
        server.shutdown()
        server.server_close()
