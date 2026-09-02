"""Tests for lineage/storage.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lineage import storage
from lineage.errors import (
    ExperimentExistsError,
    ExperimentNotFoundError,
    HasChildrenError,
    InvalidIdError,
)


def test_ensure_initialized_creates_layout(initialized: Path):
    lr = initialized / ".lineage"
    assert lr.is_dir()
    assert (lr / "experiments").is_dir()
    assert (lr / "config.json").is_file()


def test_ensure_initialized_appends_gitignore(initialized: Path):
    gi = initialized / ".gitignore"
    assert gi.is_file()
    text = gi.read_text(encoding="utf-8")
    assert ".lineage/" in text.splitlines()


def test_ensure_initialized_does_not_duplicate_gitignore(workdir: Path):
    gi = workdir / ".gitignore"
    gi.write_text("node_modules\n", encoding="utf-8")
    storage.ensure_initialized(workdir)
    text = gi.read_text(encoding="utf-8")
    # Exactly one entry mentioning .lineage (and not /lineage/).
    count = sum(
        1 for line in text.splitlines() if line.strip() in {".lineage/", ".lineage"}
    )
    assert count == 1


def test_save_and_load_meta(initialized: Path):
    meta = storage.Meta(
        id="b0",
        parent="b0",
        type="snapshot",
        message="initial",
        created_at=storage.now_iso(),
    )
    storage.save(meta, initialized)
    loaded = storage.load("b0", initialized)
    assert loaded.id == "b0"
    assert loaded.parent == "b0"
    assert loaded.type == "snapshot"
    assert loaded.message == "initial"
    assert loaded.created_at == meta.created_at


def test_save_creates_experiment_dir(initialized: Path):
    storage.save(
        storage.Meta(id="b0a", parent="b0", type="diff"),
        initialized,
    )
    assert (initialized / ".lineage" / "experiments" / "b0a").is_dir()


def test_create_experiment_dir_rejects_existing(initialized: Path):
    storage.create_experiment_dir("b0a", initialized)
    with pytest.raises(ExperimentExistsError):
        storage.create_experiment_dir("b0a", initialized)


def test_remove_experiment(initialized: Path):
    storage.create_experiment_dir("b0a", initialized)
    storage.remove_experiment("b0a", initialized)
    assert not (initialized / ".lineage" / "experiments" / "b0a").exists()


def test_remove_experiment_missing_raises(initialized: Path):
    with pytest.raises(ExperimentNotFoundError):
        storage.remove_experiment("b0a", initialized)


def test_save_rejects_invalid_id(initialized: Path):
    with pytest.raises(InvalidIdError):
        storage.save(storage.Meta(id="bad!", parent="b0", type="snapshot"), initialized)


def test_children_of(initialized: Path):
    storage.save(storage.Meta(id="b0a", parent="b0", type="diff"), initialized)
    storage.save(storage.Meta(id="b0b", parent="b0", type="diff"), initialized)
    storage.save(storage.Meta(id="b0aa", parent="b0a", type="diff"), initialized)
    children = storage.children_of("b0", initialized)
    assert set(children) == {"b0a", "b0b"}


def test_chain_to_snapshot(initialized: Path):
    storage.save(storage.Meta(id="b0", parent="b0", type="snapshot"), initialized)
    storage.save(storage.Meta(id="b0a", parent="b0", type="diff"), initialized)
    storage.save(storage.Meta(id="b0aa", parent="b0a", type="diff"), initialized)
    storage.save(storage.Meta(id="b0ab", parent="b0a", type="diff"), initialized)
    storage.save(storage.Meta(id="b0ab0", parent="b0ab", type="diff"), initialized)
    chain = storage.chain_to_snapshot("b0ab0", initialized)
    assert chain == ["b0", "b0a", "b0ab", "b0ab0"]


def test_chain_to_snapshot_self_when_snapshot(initialized: Path):
    storage.save(storage.Meta(id="b0", parent="b0", type="snapshot"), initialized)
    assert storage.chain_to_snapshot("b0", initialized) == ["b0"]


def test_find_latest(initialized: Path):
    storage.save(
        storage.Meta(id="b0", parent="b0", type="snapshot", created_at="2020-01-01T00:00:00"),
        initialized,
    )
    storage.save(
        storage.Meta(id="b0a", parent="b0", type="diff", created_at="2021-01-01T00:00:00"),
        initialized,
    )
    storage.save(
        storage.Meta(id="b0b", parent="b0", type="diff", created_at="2022-01-01T00:00:00"),
        initialized,
    )
    assert storage.find_latest(initialized) == "b0b"


def test_find_latest_returns_none_when_empty(initialized: Path):
    assert storage.find_latest(initialized) is None


def test_atomic_write_replaces_existing(tmp_path: Path):
    p = tmp_path / "x.txt"
    p.write_text("old", encoding="utf-8")
    storage.write_text_atomic(p, "new")
    assert p.read_text(encoding="utf-8") == "new"


def test_load_config_default_when_missing(tmp_path: Path):
    cfg = storage.load_config(tmp_path)
    assert cfg["auto_checkpoint_after"] == storage.DEFAULT_AUTO_CHECKPOINT_AFTER
