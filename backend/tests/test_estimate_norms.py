"""Tests for GESN norm enrichment logic: link_materials_to_works and _enrich_rows_with_gesn_norms."""
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock

# fitz (pymupdf) is not installed in the dev environment; mock before any app import
sys.modules.setdefault('fitz', MagicMock())

from app.services.estimate_parser import link_materials_to_works


def _row(type_: str, id_: str) -> dict:
    return {"id": id_, "type": type_}


# ── link_materials_to_works ──────────────────────────────────────────────────

def test_link_materials_sets_work_row_id():
    rows = [_row("work", "w1"), _row("material", "m1"), _row("material", "m2")]
    result = link_materials_to_works(rows)
    assert result[1]["work_row_id"] == "w1"
    assert result[2]["work_row_id"] == "w1"


def test_link_materials_section_does_not_break_link():
    rows = [_row("work", "w1"), _row("section", "s1"), _row("material", "m1")]
    result = link_materials_to_works(rows)
    assert result[2]["work_row_id"] == "w1"


def test_link_materials_multiple_works_in_row_links_to_last():
    """Known limitation: materials after two consecutive works link to the last work."""
    rows = [_row("work", "w1"), _row("work", "w2"), _row("material", "m1")]
    result = link_materials_to_works(rows)
    assert result[2]["work_row_id"] == "w2"


# ── _enrich_rows_with_gesn_norms ─────────────────────────────────────────────

def _make_processor():
    """Create a minimal TaskProcessor stub with only the needed async method."""
    from app.services.task_processor import TaskProcessor
    proc = object.__new__(TaskProcessor)
    return proc


def _material_with_work(mat_id: str, work_id: str) -> dict:
    return {"id": mat_id, "type": "material", "work_row_id": work_id}


def _work_row(work_id: str) -> dict:
    return {"id": work_id, "type": "work"}


@pytest.mark.asyncio
async def test_enrich_norms_stores_qty_per_work_unit():
    proc = _make_processor()
    rows = [_work_row("w1"), _material_with_work("m1", "w1")]

    claude_response = {"materials": [{"row_id": "m1", "qty_per_work_unit": 2.5, "norm_reference": "ГЭСН 08-01-003"}]}
    proc._interruptible_claude_json_with_retry = AsyncMock(return_value=claude_response)

    from app.services.task_processor import TaskProcessor
    result = await TaskProcessor._enrich_rows_with_gesn_norms(proc, rows)

    mat = next(r for r in result if r["id"] == "m1")
    assert mat["qty_per_work_unit"] == 2.5


@pytest.mark.asyncio
async def test_enrich_norms_stores_norm_reference():
    proc = _make_processor()
    rows = [_work_row("w1"), _material_with_work("m1", "w1")]

    claude_response = {"materials": [{"row_id": "m1", "qty_per_work_unit": 1.0, "norm_reference": "ГЭСН 08-01-003"}]}
    proc._interruptible_claude_json_with_retry = AsyncMock(return_value=claude_response)

    from app.services.task_processor import TaskProcessor
    result = await TaskProcessor._enrich_rows_with_gesn_norms(proc, rows)

    mat = next(r for r in result if r["id"] == "m1")
    assert mat["norm_reference"] == "ГЭСН 08-01-003"


@pytest.mark.asyncio
async def test_enrich_norms_skips_null_from_claude():
    """When Claude returns null for qty_per_work_unit the field is not written."""
    proc = _make_processor()
    rows = [_work_row("w1"), _material_with_work("m1", "w1")]

    claude_response = {"materials": [{"row_id": "m1", "qty_per_work_unit": None, "norm_reference": None}]}
    proc._interruptible_claude_json_with_retry = AsyncMock(return_value=claude_response)

    from app.services.task_processor import TaskProcessor
    result = await TaskProcessor._enrich_rows_with_gesn_norms(proc, rows)

    mat = next(r for r in result if r["id"] == "m1")
    assert "qty_per_work_unit" not in mat


@pytest.mark.asyncio
async def test_enrich_norms_tolerates_claude_error():
    """On Claude exception the rows are returned unchanged without raising."""
    proc = _make_processor()
    rows = [_work_row("w1"), _material_with_work("m1", "w1")]

    proc._interruptible_claude_json_with_retry = AsyncMock(side_effect=Exception("timeout"))

    from app.services.task_processor import TaskProcessor
    result = await TaskProcessor._enrich_rows_with_gesn_norms(proc, rows)

    mat = next(r for r in result if r["id"] == "m1")
    assert "qty_per_work_unit" not in mat
    assert len(result) == 2
