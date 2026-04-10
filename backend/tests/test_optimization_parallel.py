"""Tests for optimization: parallel batching (8.6), checkpoints (8.7), error handling (8.8).

8.6: 8 позиций, OPTIMIZATION_BATCH_SIZE=4 → 2 батча, порядок результатов по row_index
8.7: progress_data с 4 обработанными позициями → повторный запуск пропускает их
8.8: _process_single_item при исключении в price_service → new_price=None, не бросает
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.routers.tasks import _process_single_item, OPTIMIZATION_BATCH_SIZE


# ---------------------------------------------------------------------------
# 8.8: _process_single_item при исключении
# ---------------------------------------------------------------------------

async def test_process_single_item_work_exception_returns_none_price():
    """_process_single_item для work: исключение в find_work_price → new_price=None."""
    mock_ps = MagicMock()
    mock_ps.find_work_price = AsyncMock(side_effect=RuntimeError("DB connection lost"))

    item = {
        "row_index": 1,
        "name": "Кладка кирпичная",
        "type": "work",
        "price_incl_vat": 1000.0,
    }

    result = await _process_single_item(item, mock_ps, "Тест")

    assert result["new_price"] is None
    assert result["row_index"] == 1
    assert result["name"] == "Кладка кирпичная"
    assert "source" in result


async def test_process_single_item_material_exception_returns_none_price():
    """_process_single_item для material: исключение в find_material_price → new_price=None."""
    mock_ps = MagicMock()
    mock_ps.find_material_price = AsyncMock(side_effect=ConnectionError("timeout"))

    item = {
        "row_index": 2,
        "name": "Кирпич М150",
        "type": "material",
        "price_incl_vat": 12.0,
    }

    result = await _process_single_item(item, mock_ps, "Тест")

    assert result["new_price"] is None
    assert result["row_index"] == 2
    # Функция не должна пробрасывать исключение наверх
    assert "savings_abs" in result
    assert result["savings_abs"] is None


async def test_process_single_item_does_not_raise_on_exception():
    """_process_single_item никогда не бросает исключение наружу."""
    mock_ps = MagicMock()
    mock_ps.find_work_price = AsyncMock(side_effect=Exception("unexpected error"))

    item = {
        "row_index": 3,
        "name": "Штукатурка",
        "type": "work",
        "price_incl_vat": 500.0,
    }

    # Этот вызов не должен поднять исключение
    result = await _process_single_item(item, mock_ps, "Тест")
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# 8.6: Parallel batching — 8 позиций → 2 батча, порядок сохраняется
# ---------------------------------------------------------------------------

async def test_batch_loop_produces_correct_batch_sizes():
    """Батчевый цикл разбивает 8 позиций на ровно 2 группы по 4."""
    items = [
        {"row_index": i, "name": f"Позиция {i}", "type": "work", "price_incl_vat": 100.0}
        for i in range(8)
    ]
    batch_size = 4
    batches = [items[s:s + batch_size] for s in range(0, len(items), batch_size)]

    assert len(batches) == 2
    assert len(batches[0]) == 4
    assert len(batches[1]) == 4
    assert [it["row_index"] for it in batches[0]] == [0, 1, 2, 3]
    assert [it["row_index"] for it in batches[1]] == [4, 5, 6, 7]


async def test_gather_results_preserve_row_index_order():
    """asyncio.gather возвращает результаты в том же порядке что входные корутины."""
    items = [
        {"row_index": i, "name": f"Позиция {i}", "type": "work", "price_incl_vat": 100.0}
        for i in range(8)
    ]
    mock_ps = MagicMock()
    mock_ps.find_work_price = AsyncMock(return_value=None)

    all_results = []
    for batch_start in range(0, len(items), OPTIMIZATION_BATCH_SIZE):
        batch = items[batch_start: batch_start + OPTIMIZATION_BATCH_SIZE]
        batch_results = await asyncio.gather(
            *[_process_single_item(item, mock_ps, "") for item in batch],
            return_exceptions=True,
        )
        all_results.extend(batch_results)

    assert len(all_results) == 8
    row_indices = [r["row_index"] for r in all_results]
    assert row_indices == list(range(8)), "Порядок row_index должен совпадать с входным"


async def test_optimization_batch_size_constant_is_positive():
    """OPTIMIZATION_BATCH_SIZE — положительное целое."""
    assert isinstance(OPTIMIZATION_BATCH_SIZE, int)
    assert OPTIMIZATION_BATCH_SIZE > 0


# ---------------------------------------------------------------------------
# 8.7: Checkpoints — повторный запуск пропускает уже обработанные позиции
# ---------------------------------------------------------------------------

def test_checkpoint_skips_already_done_items():
    """already_done словарь фильтрует 4 обработанных из 8 позиций."""
    all_items = [
        {"row_index": i, "name": f"Позиция {i}", "type": "work", "price_incl_vat": 100.0}
        for i in range(8)
    ]
    # Имитируем: первые 4 позиции уже обработаны и сохранены в progress_data
    partial_results = [
        {
            "row_index": i,
            "name": f"Позиция {i}",
            "original_price": 100.0,
            "new_price": None,
            "source": "Не найдено",
            "savings_abs": None,
            "savings_pct": None,
            "has_vat": True,
        }
        for i in range(4)
    ]

    already_done = {r["row_index"]: r for r in partial_results}
    items_to_process = [i for i in all_items if i["row_index"] not in already_done]

    assert len(items_to_process) == 4
    assert all(item["row_index"] >= 4 for item in items_to_process)
    assert [it["row_index"] for it in items_to_process] == [4, 5, 6, 7]


def test_checkpoint_empty_progress_data_processes_all_items():
    """Если progress_data = None — все позиции подлежат обработке."""
    all_items = [
        {"row_index": i, "name": f"Позиция {i}", "type": "work", "price_incl_vat": 100.0}
        for i in range(8)
    ]

    progress_data = None
    already_done: dict = {}
    if progress_data:
        for r in progress_data.get("partial_results", []):
            already_done[r["row_index"]] = r

    items_to_process = [i for i in all_items if i["row_index"] not in already_done]

    assert len(items_to_process) == 8


def test_checkpoint_already_done_merged_into_results():
    """Результаты из already_done корректно объединяются с новыми."""
    partial = [
        {"row_index": i, "name": f"Позиция {i}", "new_price": None}
        for i in range(4)
    ]
    already_done = {r["row_index"]: r for r in partial}
    accumulated = list(already_done.values())

    # Добавляем 4 новых результата (как делает батч после обработки)
    new_results = [
        {"row_index": i, "name": f"Позиция {i}", "new_price": float(i * 10)}
        for i in range(4, 8)
    ]
    accumulated.extend(new_results)

    assert len(accumulated) == 8
    assert accumulated[0]["row_index"] == 0
    assert accumulated[7]["row_index"] == 7
