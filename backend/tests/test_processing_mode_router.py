"""
Phase 6 — нормализация processing_mode в роутере create_task.

План: plans/2026-07-21-estimate-processing-modes.md, Phase 6.
"""
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("fitz", MagicMock())

from app.routers.tasks import _resolve_processing_mode  # noqa: E402


def test_default_is_fast():
    assert _resolve_processing_mode("ESTIMATE_FROM_LIST", None) == "fast"


def test_batch_allowed_for_estimate():
    assert _resolve_processing_mode("ESTIMATE_FROM_LIST", "batch") == "batch"


def test_batch_forced_to_fast_for_other_types():
    assert _resolve_processing_mode("LIST_FROM_GRAND", "batch") == "fast"


def test_invalid_value_falls_back_to_fast():
    assert _resolve_processing_mode("ESTIMATE_FROM_LIST", "turbo") == "fast"


def test_case_insensitive():
    assert _resolve_processing_mode("ESTIMATE_FROM_LIST", "BATCH") == "batch"
