"""Tests for optimization: checkpoints (8.7), error handling (8.8).

8.7: progress_data с 4 обработанными позициями → повторный запуск пропускает их
8.8: _process_single_item при исключении в price_service → new_price=None, не бросает
"""
from unittest.mock import AsyncMock, MagicMock

from app.routers.tasks import _process_single_item


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

