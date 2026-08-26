"""Оборванный ответ на стадии полноты дробит чанк, а не роняет стадию.

Проверка полноты дописывает к работам недостающие материалы, поэтому ответ
длиннее входа и плотный чанк упирается в лимит. Раньше это валило стадию
сообщением «Ответ слишком большой, разбейте выполнение на подэтапы».

Дно рекурсии здесь ведёт себя иначе, чем на перечне: позиция уже есть в
перечне и поедет дальше в смету, поэтому она возвращается как есть — с
пометкой, что полноту по ней никто не сверял.

План: plans/2026-08-26-oborvannyj-otvet-perechnya.md
"""
import sys
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("fitz", MagicMock())

from app.services.claude_service import ResponseTruncatedError  # noqa: E402
from app.services.task_processor import (  # noqa: E402
    COMPLETENESS_SKIPPED_NOTE,
    TaskProcessor,
    _split_items_in_half,
)


def _work(name: str, source_no: str = "") -> dict:
    item = {"type": "Работа", "name": name, "unit": "м2", "quantity": 10}
    if source_no:
        item["source_no"] = source_no
    return item


def _material(name: str, source_no: str = "") -> dict:
    item = {"type": "Материал", "name": name, "unit": "шт", "quantity": 5}
    if source_no:
        item["source_no"] = source_no
    return item


# --- деление чанка позиций ------------------------------------------------


def test_split_cuts_on_work_boundary():
    """Материалы не отрываются от своей работы: граница — позиция «Работа»."""
    chunk = [
        _work("Работа 1"), _material("Материал 1.1"), _material("Материал 1.2"),
        _work("Работа 2"), _material("Материал 2.1"), _material("Материал 2.2"),
    ]

    left, right = _split_items_in_half(chunk)

    assert [it["name"] for it in left] == ["Работа 1", "Материал 1.1", "Материал 1.2"]
    assert [it["name"] for it in right] == ["Работа 2", "Материал 2.1", "Материал 2.2"]


def test_split_falls_back_to_middle_without_work():
    """Работы в чанке нет — режем по середине."""
    chunk = [_material(f"Материал {i}") for i in range(6)]

    left, right = _split_items_in_half(chunk)

    assert len(left) == 3 and len(right) == 3


def test_split_always_shrinks_both_halves():
    """Деление обязано сходиться: пустых половин быть не может."""
    for size in range(2, 30):
        chunk = [_work(f"Работа {i}") for i in range(size)]
        left, right = _split_items_in_half(chunk)
        assert 0 < len(left) < size
        assert 0 < len(right) < size
        assert len(left) + len(right) == size


def test_split_bottom_is_single_item():
    """Одна позиция — делить нечего."""
    assert _split_items_in_half([_work("Работа 1")]) is None
    assert _split_items_in_half([]) is None


# --- чанк стадии полноты --------------------------------------------------


def _processor(monkeypatch, answer):
    """Обработчик с подменённым ИИ: `answer(prompt_text)` → dict или исключение."""
    processor = TaskProcessor("tid-completeness", db=MagicMock())
    messages: list = []

    async def fake_progress(message: str) -> None:
        messages.append(message)

    async def fake_claude(msgs, *args, **kwargs) -> dict:
        return answer(msgs[0]["content"])

    monkeypatch.setattr(processor, "update_progress", fake_progress)
    monkeypatch.setattr(processor, "_interruptible_claude_json_with_retry", fake_claude)
    return processor, messages


@pytest.mark.asyncio
async def test_truncated_chunk_is_split(monkeypatch):
    """Целый чанк не помещается — считаем половины и складываем результат."""
    calls: list = []

    def answer(prompt: str) -> dict:
        calls.append(prompt)
        if "Перегородки ГКЛ" in prompt and "Облицовка ГКЛ" in prompt:
            raise ResponseTruncatedError("Ответ слишком большой")
        if "Перегородки ГКЛ" in prompt:
            return {
                "items": [
                    {"type": "Работа", "name": "Перегородки ГКЛ", "unit": "м2", "quantity": 10},
                    {"type": "Материал", "name": "Профиль ПН-2", "unit": "м", "quantity": 12},
                ],
                "changes_summary": "Добавлен профиль",
            }
        return {
            "items": [
                {"type": "Работа", "name": "Облицовка ГКЛ", "unit": "м2", "quantity": 10},
                {"type": "Материал", "name": "Лист ГКЛ", "unit": "м2", "quantity": 11},
            ],
            "changes_summary": "Добавлен лист",
        }

    processor, messages = _processor(monkeypatch, answer)
    chunk = [_work("Перегородки ГКЛ", "1"), _work("Облицовка ГКЛ", "2")]

    items, lost, summaries = await processor._check_completeness_chunk(chunk, "1/1")

    # Оборванный чанк + две половины.
    assert len(calls) == 3
    assert [it["name"] for it in items] == [
        "Перегородки ГКЛ", "Профиль ПН-2", "Облицовка ГКЛ", "Лист ГКЛ",
    ]
    # Номера сопоставлены со своей половиной: дописанный материал номера не получил.
    assert [it.get("source_no") for it in items] == ["1", None, "2", None]
    assert lost == []
    assert summaries == ["Добавлен профиль", "Добавлен лист"]


@pytest.mark.asyncio
async def test_bottom_keeps_item_with_note(monkeypatch):
    """Даже одна позиция не поместилась — она остаётся в перечне с пометкой."""
    def answer(prompt: str) -> dict:
        raise ResponseTruncatedError("Ответ слишком большой")

    processor, messages = _processor(monkeypatch, answer)
    chunk = [_work("Перегородки ГКЛ", "7")]

    items, lost, summaries = await processor._check_completeness_chunk(chunk, "1/1")

    assert [it["name"] for it in items] == ["Перегородки ГКЛ"]
    # Позиция цела: объём и номер на месте, потерянной она не считается.
    assert items[0]["quantity"] == 10
    assert items[0]["source_no"] == "7"
    assert lost == []
    assert summaries == []
    # Про непроверенную полноту сказано и в файле, и в ходе выполнения.
    assert COMPLETENESS_SKIPPED_NOTE in items[0]["notes"]
    assert any(m.startswith("⚠") for m in messages)


@pytest.mark.asyncio
async def test_bottom_note_does_not_erase_existing_note(monkeypatch):
    """Прежнее примечание позиции пометка не затирает."""
    def answer(prompt: str) -> dict:
        raise ResponseTruncatedError("Ответ слишком большой")

    processor, _ = _processor(monkeypatch, answer)
    chunk = [dict(_work("Перегородки ГКЛ", "7"), notes="Материал заказчика")]

    items, _, _ = await processor._check_completeness_chunk(chunk, "1/1")

    assert items[0]["notes"] == f"Материал заказчика; {COMPLETENESS_SKIPPED_NOTE}"
