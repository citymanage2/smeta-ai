"""Тесты белого списка build_progress_summary — счётчики есть, чувствительного нет."""
from app.utils.progress_summary import build_progress_summary

# Ключи progress_data, которые НИКОГДА не должны утечь на фронт.
_FORBIDDEN = [
    "items", "ocr_pages", "ocr_pages_partial", "claude_results",
    "matched", "unmatched", "proposals", "abc_breakdown",
    "summaries", "batch_id", "current_date", "new_version_id",
    "error", "_stage",
]


def test_none_and_empty():
    assert build_progress_summary(None) is None
    assert build_progress_summary({}) is None
    assert build_progress_summary("not a dict") is None  # type: ignore[arg-type]


def test_chunk_counters_pass_through():
    out = build_progress_summary({"chunks_done": 2, "total_chunks": 5, "partial_count": 1})
    assert out == {"chunks_done": 2, "total_chunks": 5, "partial_count": 1}


def test_items_reduced_to_count_only():
    heavy = [{"name": "Бетон", "work_price": 1000, "sources": "secret-url"} for _ in range(7)]
    out = build_progress_summary({"chunks_done": 1, "total_chunks": 2, "items": heavy})
    assert out is not None
    assert out["items_count"] == 7
    assert "items" not in out  # содержимое позиций не уходит


def test_optimization_chunks_total_normalized():
    out = build_progress_summary({"opt_step": "abc", "chunks_done": 0, "chunks_total": 1})
    assert out is not None
    assert out["opt_step"] == "abc"
    assert out["total_chunks"] == 1  # chunks_total нормализован к total_chunks


def test_sensitive_fields_are_stripped():
    dirty = {
        "chunks_done": 3,
        "total_chunks": 4,
        "items": [{"name": "x", "material_price": 500}],
        "ocr_pages": ["страница с сырым текстом сметы"],
        "ocr_pages_partial": ["ещё страница"],
        "claude_results": {"0": {"work_price": 999, "sources": "http://internal"}},
        "matched": {"0": {"price_list_name": "Кеш"}},
        "unmatched": {"1": {"name": "y"}},
        "proposals": [{"id": "p1"}],
        "abc_breakdown": {"A": 10},
        "summaries": ["внутренняя сводка"],
        "batch_id": "msgbatch_secret",
        "current_date": "2026-07-24",
        "new_version_id": "ver-1",
        "error": "traceback внутренностей",
        "_stage": "pre_excel",
    }
    out = build_progress_summary(dirty)
    assert out is not None
    for forbidden in _FORBIDDEN:
        assert forbidden not in out, f"поле {forbidden!r} не должно уходить на фронт"
    # Полезные счётчики сохранены.
    assert out["chunks_done"] == 3
    assert out["total_chunks"] == 4
    assert out["items_count"] == 1


def test_bool_not_treated_as_int():
    out = build_progress_summary({"chunks_done": True, "total_chunks": 5})
    assert out == {"total_chunks": 5}  # True (bool) отброшен, не попал как 1
