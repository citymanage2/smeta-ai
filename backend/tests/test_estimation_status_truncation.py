"""
Regression test: estimation_status values must fit within the VARCHAR column length.

Reproduces production StringDataRightTruncationError:
  value 'processing_optimization' (23 chars) does not fit in VARCHAR(20).
"""
import pytest
from app.models.task import Task
from app.constants import ESTIMATION_STATUS_LABELS


def test_estimation_status_values_fit_column():
    """All ESTIMATION_STATUS_LABELS keys must fit within VARCHAR column length."""
    col = Task.__table__.c["estimation_status"]
    max_len = col.type.length

    violations = [
        f"{key!r} ({len(key)} chars)"
        for key in ESTIMATION_STATUS_LABELS
        if len(key) > max_len
    ]

    assert not violations, (
        f"estimation_status values exceed VARCHAR({max_len}): {violations}"
    )
