"""Единица сверяется и при доборе цен, и при пересчёте одной строки.

Основной проход сметы цену за мешок в позицию с килограммами больше не пустит,
а вот кнопки «Исправить пустые цены» и «Цена» ходят к ИИ отдельно. Если правило
живёт только в основном проходе, ошибка возвращается через кнопку — теми же
разами, только по одной строке.

Спека: specs/2026-08-06-edinica-izmereniya-v-podbore-ceny.md
"""
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.modules.setdefault("fitz", MagicMock())

from app.services.task_processor import TaskProcessor  # noqa: E402
from app.utils.unit_compat import (  # noqa: E402
    PRICE_CONVERTED_PREFIX,
    PRICE_UNIT_MISMATCH_PREFIX,
    prices_for_unit,
)


# ---------------------------------------------------------------------------
# Общее правило для ответа ИИ
# ---------------------------------------------------------------------------

def test_cena_za_meshok_v_pozicii_v_kg_ne_beretsya():
    work, material, notes = prices_for_unit(None, 500.0, "мешок", "кг")
    assert material is None
    assert work is None
    assert any(PRICE_UNIT_MISMATCH_PREFIX in n for n in notes)


def test_cena_za_tonnu_pereschityvaetsya():
    work, material, notes = prices_for_unit(None, 73770.0, "т", "кг")
    assert material == 73.77
    assert any(PRICE_CONVERTED_PREFIX in n for n in notes)


def test_sovpavshaya_edinica_bez_pometok():
    work, material, notes = prices_for_unit(180.0, None, "м2", "м2")
    assert work == 180.0
    assert notes == []


def test_ii_ne_ukazal_edinicu_cena_beretsya():
    """ИИ не вернул unit — возражать нечем, поведение прежнее."""
    work, material, notes = prices_for_unit(180.0, None, None, "м2")
    assert work == 180.0
    assert notes == []


# ---------------------------------------------------------------------------
# Добор пустых цен
# ---------------------------------------------------------------------------

def _proc(items: list[dict]) -> TaskProcessor:
    db = MagicMock()
    db.commit = AsyncMock()
    task = MagicMock()
    task.status = "processing"
    task.processing_mode = "sync"
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=task))
    )
    p = TaskProcessor("tid-fix", db=db)
    p.update_progress = AsyncMock(return_value=None)
    p._check_cancelled = AsyncMock(return_value=None)
    return p


async def _run_fix(monkeypatch, items, ai_answer) -> list[dict]:
    """Прогнать добор пустых цен с заданным ответом ИИ, вернуть позиции после."""
    from app.services import estimate_store, task_processor as tp

    saved: dict = {}

    async def _read_items(db, task):
        return items

    async def _write_items(db, task, new_items, commit=True):
        saved["items"] = new_items
        return (new_items, 0.0)

    monkeypatch.setattr(estimate_store, "read_items", _read_items)
    monkeypatch.setattr(estimate_store, "write_items", _write_items)

    async def _run_all(workers, **kwargs):
        return [await worker() for worker in workers]

    p = _proc(items)
    p._call_claude_json_with_retry = AsyncMock(return_value={"items": ai_answer})
    p._run_chunks_parallel = _run_all

    await tp.TaskProcessor.fix_empty_prices(p)
    assert "items" in saved, "смета не была пересохранена — добор не дошёл до слияния"
    return saved["items"]


async def test_dobor_ne_pishet_cenu_za_meshok(monkeypatch):
    items = [{"type": "Материал", "name": "Смеси сухие", "unit": "кг",
              "quantity": 30, "material_price": None}]
    ai = [{"id": 0, "type": "Материал", "unit": "мешок", "material_price": 500.0}]

    result = await _run_fix(monkeypatch, items, ai)

    assert result[0]["material_price"] is None
    assert PRICE_UNIT_MISMATCH_PREFIX in result[0]["notes"]


async def test_dobor_pereschityvaet_svodimuyu_edinicu(monkeypatch):
    items = [{"type": "Работа", "name": "Окраска", "unit": "м2",
              "quantity": 1061, "work_price": None}]
    ai = [{"id": 0, "type": "Работа", "unit": "100 м2", "work_price": 18000.0}]

    result = await _run_fix(monkeypatch, items, ai)

    assert result[0]["work_price"] == 180.0
    assert PRICE_CONVERTED_PREFIX in result[0]["notes"]


# ---------------------------------------------------------------------------
# Промпт пересчёта одной строки
# ---------------------------------------------------------------------------

def test_promt_pereschyota_trebuet_edinicu_pozicii():
    """Требование живёт в тексте запроса — без него ИИ вернёт цену за упаковку."""
    import inspect

    from app.routers import tasks as tasks_router

    source = inspect.getsource(tasks_router.reprice_estimate_item)
    assert "за 1 (одну) единицу измерения позиции" in source
    assert '"unit"' in source
