"""Custom exceptions for lineage."""

from __future__ import annotations


class LineageError(Exception):
    """Base class for all lineage errors."""


class InvalidIdError(LineageError):
    """An experiment ID is malformed."""


class ExperimentNotFoundError(LineageError):
    """Referenced experiment does not exist."""


class ExperimentExistsError(LineageError):
    """An experiment with this ID already exists."""


class HasChildrenError(LineageError):
    """Tried to remove an experiment that has children (use --recursive)."""

    def __init__(self, exp_id: str, child_count: int):
        super().__init__(
            f"Experiment {exp_id} has {child_count} child(ren). "
            f"Use --recursive to remove them too."
        )
        self.exp_id = exp_id
        self.child_count = child_count


class NotImplemented(LineageError):
    """Command exists in spec but is not yet implemented in v0.1."""
