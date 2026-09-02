"""Pure-Python unified diff generation and application.

The output format matches ``diff -ruN`` (the format the spec calls for), so
``patch -p1 < diff.patch`` would also accept it. The applier is intentionally
restricted to the subset we produce ourselves — sufficient for lineage's needs,
and deterministic across macOS, Linux, and Windows without external binaries.
"""

from __future__ import annotations

import difflib
import io
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .errors import LineageError

# --- Diff generation -------------------------------------------------------

DEFAULT_CONTEXT = 3


def _splitlines_keepends(text: str) -> list[str]:
    """Split ``text`` into lines, preserving the line terminator on each line.

    Like ``str.splitlines(keepends=True)`` but a final unterminated line still
    gets an entry.
    """
    if not text:
        return []
    parts = text.splitlines(keepends=True)
    if text.endswith("\n") or text.endswith("\r"):
        return parts
    # No trailing newline: synthesize one so the last "line" is still emitted.
    if parts:
        return parts
    return [text]


def make_unified_diff(
    old: dict[str, bytes],
    new: dict[str, bytes],
    old_label: str = "a",
    new_label: str = "b",
    context: int = DEFAULT_CONTEXT,
) -> str:
    """Return a ``diff -ruN``-compatible patch string.

    ``old`` and ``new`` map relative posix paths to file contents. Binary files
    are skipped (a one-line marker is emitted instead of a real diff); this is
    an explicit v0.1 limitation, documented in the README.
    """
    out = io.StringIO()
    all_paths = sorted(set(old) | set(new))
    for path in all_paths:
        old_data = old.get(path, None)
        new_data = new.get(path, None)
        # Treat identical contents as no change.
        if old_data is not None and new_data is not None and old_data == new_data:
            continue
        old_text = _safe_decode(old_data) if old_data is not None else ""
        new_text = _safe_decode(new_data) if new_data is not None else ""
        # If either side is not utf-8 decodable, emit a binary marker.
        if (old_data is not None and old_text is None) or (
            new_data is not None and new_text is None
        ):
            _write_binary_marker(out, path, old_data, new_data)
            continue

        if old_text == new_text:
            continue

        is_new = old_data is None
        is_deleted = new_data is None
        old_lines = _splitlines_keep_terminator(old_text) if not is_new else []
        new_lines = _splitlines_keep_terminator(new_text) if not is_deleted else []
        from_label = "/dev/null" if is_new else f"a/{path}"
        to_label = "/dev/null" if is_deleted else f"b/{path}"
        diff_iter = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=from_label,
            tofile=to_label,
            fromfiledate="",
            tofiledate="",
            n=context,
            lineterm="\n",
        )
        for line in diff_iter:
            out.write(line)
            if not line.endswith("\n"):
                out.write("\n")
    return out.getvalue()


def _write_binary_marker(
    out: io.StringIO, path: str, old_data: bytes | None, new_data: bytes | None
) -> None:
    """Emit a single 'Binary files differ' line for a binary file pair."""
    if old_data is None and new_data is not None:
        out.write(f"diff --git a/{path} b/{path}\n")
        out.write("new file mode 100644\n")
        out.write("--- /dev/null\n")
        out.write(f"+++ b/{path}\n")
        out.write(f"Binary files /dev/null and b/{path} differ\n")
    elif new_data is None and old_data is not None:
        out.write(f"diff --git a/{path} b/{path}\n")
        out.write("deleted file mode 100644\n")
        out.write(f"--- a/{path}\n")
        out.write("--- /dev/null\n")
        out.write(f"Binary files a/{path} and /dev/null differ\n")
    else:
        out.write(f"diff --git a/{path} b/{path}\n")
        out.write(f"--- a/{path}\n")
        out.write(f"+++ b/{path}\n")
        out.write(f"Binary files a/{path} and b/{path} differ\n")


def _splitlines_keep_terminator(text: str) -> list[str]:
    """Return lines, each terminated with ``\n`` (so difflib emits full lines)."""
    if text == "":
        return []
    lines = text.splitlines(keepends=True)
    # Normalize CRLF to LF for diff purposes (we still re-emit the right endings
    # at apply time).
    norm: list[str] = []
    for line in lines:
        if line.endswith("\r\n"):
            norm.append(line[:-2] + "\n")
        else:
            norm.append(line)
    # If the original ended without a newline, splitlines(keepends=True) still
    # emits the last line without a terminator; add one to keep hunks clean.
    if not text.endswith(("\n", "\r")) and norm and not norm[-1].endswith("\n"):
        norm[-1] = norm[-1] + "\n"
    return norm


def _safe_decode(data: bytes | None) -> str | None:
    """Decode ``data`` as UTF-8 (lossless). Return None for binary/undecodable."""
    if data is None:
        return None
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return decoded


# --- Diff application ------------------------------------------------------


@dataclass
class FileState:
    """Mutable in-memory file state used by ``apply_patch_text``."""

    files: dict[str, bytes] = field(default_factory=dict)

    def get(self, path: str) -> bytes | None:
        return self.files.get(path)

    def set(self, path: str, data: bytes) -> None:
        self.files[path] = data

    def delete(self, path: str) -> None:
        self.files.pop(path, None)

    def has(self, path: str) -> bool:
        return path in self.files


_HUNK_RE = re.compile(
    r"^@@ -(?P<a_start>\d+)(?:,(?P<a_count>\d+))? \+(?P<b_start>\d+)(?:,(?P<b_count>\d+))? @@"
)
_FILE_HEADER_RE = re.compile(r"^\+\+\+ (?P<b>\S+)|^--- (?P<a>\S+)")
_GIT_NEW_RE = re.compile(r"^diff --git a/(?P<path>.+) b/(?P<path2>.+)$")


@dataclass
class _FileDiff:
    old_path: str | None
    new_path: str | None
    is_new: bool = False
    is_deleted: bool = False
    is_binary: bool = False
    hunks: list[tuple[int, list[str]]] = field(default_factory=list)
    # Each hunk is (b_start_1indexed, list of normalized lines including
    # leading ' '/'+'/'-').

    @property
    def b_path(self) -> str | None:
        return self.new_path or self.old_path


def _parse_patch(patch: str) -> list[_FileDiff]:
    """Parse a unified diff into per-file diffs.

    Tolerates ``diff --git`` headers (we ignore the extended git header lines),
    ``---``/``+++`` file headers, and ``@@`` hunk headers. We only use the ``+``
    side numbering when applying, which is what we need to reconstruct the
    "new" file.
    """
    diffs: list[_FileDiff] = []
    cur: _FileDiff | None = None
    expect_a = False
    expect_b = False

    def _start_new() -> _FileDiff:
        d = _FileDiff(old_path=None, new_path=None)
        diffs.append(d)
        return d

    def _strip_prefix(p: str) -> str:
        if p.startswith("a/") or p.startswith("b/"):
            return p[2:]
        return p

    for raw in patch.splitlines(keepends=True):
        # Strip the trailing newline for header detection, but keep it in
        # hunk body lines so the applier can preserve line terminators.
        stripped = raw.rstrip("\n").rstrip("\r")
        line = stripped
        newline = ""
        if raw.endswith("\r\n"):
            newline = "\r\n"
        elif raw.endswith("\n"):
            newline = "\n"
        if line.startswith("diff --git "):
            cur = _start_new()
            expect_a = False
            expect_b = False
            continue
        if line.startswith("--- "):
            # If we already have hunks for the current file, this is a new file.
            if cur is None or (cur.hunks):
                cur = _start_new()
            m = _FILE_HEADER_RE.match(line)
            a = m.group("a") if m else None
            if a is None:
                # Try plain "--- a/path"
                a = line[4:].split("\t", 1)[0].strip()
            if a == "/dev/null":
                cur.is_new = True
                cur.old_path = None
            else:
                cur.old_path = _strip_prefix(a)
            expect_b = True
            continue
        if line.startswith("+++ "):
            m = _FILE_HEADER_RE.match(line)
            b = m.group("b") if m else None
            if b is None:
                b = line[4:].split("\t", 1)[0].strip()
            if b == "/dev/null":
                cur.is_deleted = True
                cur.new_path = None
            else:
                cur.new_path = _strip_prefix(b)
            expect_a = False
            expect_b = False
            continue
        m = _HUNK_RE.match(line)
        if m and cur is not None:
            b_start = int(m.group("b_start"))
            cur.hunks.append((b_start, []))
            continue
        if line.startswith("Binary files"):
            # Binary-file marker — may appear before or after a hunk header,
            # depending on the producer.
            if cur is not None:
                cur.is_binary = True
            continue
        if cur is not None and cur.hunks:
            # Part of a hunk body. Preserve the line terminator.
            if line.startswith((" ", "+", "-")):
                body_line = line + newline if newline else line
                cur.hunks[-1][1].append(body_line)
            elif line == "":
                # Allow blank lines as context (rare but seen in some producers).
                cur.hunks[-1][1].append(" " + newline if newline else " ")
            else:
                # Unknown line; ignore.
                continue
    return [d for d in diffs if d.b_path is not None or d.old_path is not None]


def apply_patch_text(state: FileState, patch: str, reverse: bool = False) -> None:
    """Apply ``patch`` to ``state`` in place.

    Supports only the unified-diff subset we produce: text files, ``diff -ruN``-
    style headers, ``@@`` hunks. Binary "Binary files differ" hunks are not
    supported and will raise ``LineageError``.
    """
    diffs = _parse_patch(patch)
    for fd in diffs:
        if fd.is_binary:
            raise LineageError(
                "Cannot apply patch containing binary file hunk; "
                "reconstruct the snapshot instead."
            )
        if reverse:
            _apply_file_reverse(state, fd)
        else:
            _apply_file_forward(state, fd)


def _apply_file_forward(state: FileState, fd: _FileDiff) -> None:
    if fd.is_deleted:
        # File was deleted: just drop it from state.
        if fd.old_path is not None:
            state.delete(fd.old_path)
        return
    path = fd.b_path
    if path is None:
        return
    if fd.is_new:
        new_text = ""
    else:
        old_data = state.get(path) if path else None
        old_text = old_data.decode("utf-8") if old_data is not None else ""
        new_text = old_text
    _build_new_text(state, fd, path, new_text, forward=True)


def _apply_file_reverse(state: FileState, fd: _FileDiff) -> None:
    path = fd.b_path
    if fd.is_new:
        # The forward diff was "new file"; reverse deletes it.
        if path is not None:
            state.delete(path)
        return
    if fd.is_deleted:
        # Forward diff was "delete file"; reverse recreates it from the hunks.
        if fd.old_path is None:
            return
        text = ""
        _build_new_text(state, fd, fd.old_path, text, forward=False)
        return
    if path is None:
        return
    current = state.get(path)
    current_text = current.decode("utf-8") if current is not None else ""
    _build_new_text(state, fd, path, current_text, forward=False)


def _build_new_text(
    state: FileState,
    fd: _FileDiff,
    path: str,
    base_text: str,
    forward: bool,
) -> None:
    """Apply each hunk to ``base_text`` and write the result to ``state``."""
    cur_text = base_text
    for b_start, body in fd.hunks:
        cur_text = _apply_hunk(cur_text, b_start, body, forward=forward)
    if cur_text == "" and not fd.is_new and forward:
        # File became empty: still write it (empty file is a valid state).
        pass
    state.set(path, cur_text.encode("utf-8"))


def _apply_hunk(
    text: str, b_start_1indexed: int, body: list[str], forward: bool
) -> str:
    """Apply a single hunk to ``text`` and return the new text.

    ``b_start_1indexed`` is the 1-based starting line in the ``b`` file (or the
    ``a`` file when reversing). We work with line offsets starting at 0 in our
    internal representation, so convert.
    """
    lines = text.splitlines(keepends=True) if text else []
    # If text doesn't end with newline, splitlines(keepends=True) still returns
    # the last line without a terminator — that's fine, we keep the terminator
    # state in the line itself.

    if forward:
        old_lines, new_lines = _split_hunk(body)
    else:
        new_lines, old_lines = _split_hunk(body)

    # b_start_1indexed is the starting line (1-based) in the "b" side for
    # forward; in reverse, it's the starting line in the current text (which
    # corresponds to the original "b" side).
    start_0 = max(0, b_start_1indexed - 1)
    out = lines[:start_0]
    out.extend(new_lines)
    # Skip the original block that was replaced.
    end_of_replaced = start_0 + len(old_lines)
    out.extend(lines[end_of_replaced:])
    return "".join(out)


def _split_hunk(body: list[str]) -> tuple[list[str], list[str]]:
    """Split hunk body lines into ``(old_lines, new_lines)``.

    Lines starting with ``-`` go to old, ``+`` to new, `` `` to both.
    """
    old: list[str] = []
    new: list[str] = []
    for line in body:
        if not line:
            continue
        tag = line[0]
        content = line[1:]
        # Preserve the original terminator: difflib emits \n; the content
        # already includes the trailing \n for non-empty lines.
        if tag == "-":
            old.append(content)
        elif tag == "+":
            new.append(content)
        elif tag == " ":
            old.append(content)
            new.append(content)
        else:
            # Unknown tag — treat as context to be safe.
            old.append(content)
            new.append(content)
    return old, new
