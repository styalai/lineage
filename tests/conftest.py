"""Shared pytest fixtures."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Make sure the package is importable when running `pytest` from the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A clean CWD pointing at a fresh temp dir."""
    d = tmp_path / "project"
    d.mkdir()
    monkeypatch.chdir(d)
    return d


@pytest.fixture
def initialized(workdir: Path) -> Path:
    """A workdir with ``.lineage/`` already created."""
    from lineage import storage

    storage.ensure_initialized(workdir)
    return workdir


def write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def writeb(p: Path, data: bytes) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
