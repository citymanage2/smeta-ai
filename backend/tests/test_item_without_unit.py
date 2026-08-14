"""Позиция без единицы измерения не роняет расчёт цен.

Смета строится из позиций перечня/полноты, а те приходят из ответа ИИ: поле
«unit» он возвращает не всегда. Раньше шаг расчёта цен брал его по ключу, и
одна дырявая позиция валила весь этап — на середине, уже оплаченными чанками, с
текстом ошибки «'unit'», по которому ничего не понять.

План: plans/2026-08-14-poziciya-bez-edinicy-ronyala-smetu.md
"""
import json
import sys
from unittest.mock import AsyncMock, MagicMock

sys.modules.setdefault("fitz", MagicMock())

from app.services.task_processor import TaskProcessor  # noqa: E402
from app.utils.error_text import describe_exception  # noqa: E402
from app.utils.item_contract import ensure_item_fields  # noqa: E402


def _proc() -> TaskProcessor:
    p = TaskProcessor("tid-no-unit", db=MagicMock())
    p.update_progress = AsyncMock(return_value=None)
    p._save_progress_data = AsyncMock(return_value=None)
    return p


# --------------------------------------------------------------------------
# Контракт позиции
# --------------------------------------------------------------------------

def test_missing_fields_are_added_empty():
    items = ensure_item_fields([{"name": "Штукатурка стен"}])
    assert items[0] == {"name": "Штукатурка стен", "type": "", "unit": "", "quantity": None}


def test_existing_values_are_not_touched():
    items = ensure_item_fields([
        {"type": "Работа", "name": "Кладка", "unit": "м3", "quantity": 12.5, "notes": "х"},
    ])
    assert items[0]["unit"] == "м3"
    assert items[0]["quantity"] == 12.5
    assert items[0]["notes"] == "х"


def test_null_unit_becomes_empty_string():
    """`"unit": null` от ИИ — та же дырка, что и отсутствующий ключ."""
    items = ensure_item_fields([{"name": "Грунтовка", "unit": None}])
    assert items[0]["unit"] == ""


def test_non_dict_rows_pass_through():
    assert ensure_item_fields(["мусор", None]) == ["мусор", None]


def test_source_list_is_not_mutated():
    original = [{"name": "A"}]
    ensure_item_fields(original)
    assert original == [{"name": "A"}]


# --------------------------------------------------------------------------
# Отправка чанка в Claude — позиция без единицы доезжает, а не падает
# --------------------------------------------------------------------------

async def test_price_chunk_survives_item_without_unit():
    p = _proc()
    captured: dict = {}

    async def fake_call(messages, **kwargs):
        captured["prompt"] = messages[0]["content"]
        return {"items": [{"id": 0, "work_price": 100}]}

    p._call_claude_json_with_retry = AsyncMock(side_effect=fake_call)

    chunk = [
        {"_id": 0, "type": "Работа", "name": "Монтаж ОПС"},          # ни unit, ни quantity
        {"_id": 1, "type": "Материал", "name": "Кабель", "unit": "м", "quantity": 40},
    ]
    result = await p._fetch_price_chunk(chunk, "2026-08-14", "chunk-0")

    assert result == [{"id": 0, "work_price": 100}]
    # Позиция без единицы уехала в промпт с пустой единицей, а не потерялась.
    assert '"unit": ""' in captured["prompt"]
    assert "Монтаж ОПС" in captured["prompt"]


async def test_batch_request_survives_item_without_unit(monkeypatch):
    p = _proc()
    p._save_claude_partial = AsyncMock(return_value=None)

    captured: dict = {}

    def fake_build(custom_id, messages, system_prompt=None, use_web_search=False):
        captured.setdefault("prompts", []).append(messages[0]["content"])
        return {"custom_id": custom_id}

    async def fake_submit(requests):
        captured["count"] = len(requests)
        return "batch-1"

    monkeypatch.setattr("app.services.task_processor.build_batch_request", fake_build)
    monkeypatch.setattr("app.services.task_processor.submit_claude_batch", fake_submit)

    chunks = [[{"_id": 0, "type": "Работа", "name": "Монтаж ОПС"}]]
    await p._submit_estimate_batch(
        task=MagicMock(), items=[], matched_by_gidx={}, unmatched_by_gidx={},
        current_date="2026-08-14", chunks=chunks,
    )

    assert captured["count"] == 1
    assert '"unit": ""' in captured["prompts"][0]


# --------------------------------------------------------------------------
# Текст ошибки — род ошибки виден, а не голое «'unit'»
# --------------------------------------------------------------------------

def test_key_error_gets_its_type_in_message():
    assert describe_exception(KeyError("unit")) == "KeyError: 'unit'"


def test_russian_message_passes_through():
    assert describe_exception(ValueError("Исходная задача не найдена")) == (
        "Исходная задача не найдена"
    )


def test_empty_message_falls_back_to_type():
    assert describe_exception(TimeoutError()) == "TimeoutError"


def test_json_error_keeps_its_text():
    err = json.JSONDecodeError("Expecting value", "doc", 0)
    described = describe_exception(err)
    assert described.startswith("JSONDecodeError: ")
    assert "Expecting value" in described
