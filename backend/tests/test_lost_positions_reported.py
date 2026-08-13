"""Задача перечня говорит вслух, какие позиции ЛСР не вернул ИИ.

Проверка не самого сопоставления (оно в test_lost_positions_warning.py), а
связки: обработчик перечня из гранд-сметы сверяет ответ модели со строками
файла и пишет предупреждение в ход выполнения задачи.

План: plans/2026-08-14-propusk-pozicij-iz-grand-smety.md, Фаза 3.
"""
import io
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import openpyxl
import pytest

sys.modules.setdefault("fitz", MagicMock())

from app.services.task_processor import TaskProcessor  # noqa: E402


def _grand_xlsx() -> bytes:
    """Три позиции ЛСР: работа и два прибора с номерами 2, 3, 5."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ЛОКАЛЬНЫЙ СМЕТНЫЙ РАСЧЕТ (СМЕТА) № 1"])
    ws.append(["№ п/п", "Обоснование", "Наименование работ и затрат",
               "Единица измерения", "Количество"])
    ws.append([2, "ГЭСНм10-08-001-11", "Устройства промежуточные на количество лучей: 10", "шт", 1])
    ws.append([3, "ТЦ_89.1.61.02", "Контроллер Панель-2-ПРО (S3) исп.Л", "шт", 1])
    ws.append([5, "ТЦ_89.1.61.03", "Извещатель ИП 212-141 исп.01", "шт", 113])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _processor(monkeypatch, ai_items: list) -> tuple[TaskProcessor, list]:
    """Обработчик, у которого ИИ отвечает `ai_items`, а БД подменена."""
    processor = TaskProcessor("tid-lost", db=MagicMock())
    messages: list = []

    async def fake_progress(message: str) -> None:
        messages.append(message)

    async def fake_claude(*args, **kwargs) -> dict:
        return {"items": ai_items}

    async def noop(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(processor, "update_progress", fake_progress)
    monkeypatch.setattr(processor, "_call_claude_json_with_retry", fake_claude)
    monkeypatch.setattr(processor, "_check_cancelled", noop)
    monkeypatch.setattr(processor, "_save_progress_data", noop)
    monkeypatch.setattr(processor, "save_result", noop)
    monkeypatch.setattr(processor, "_create_initial_generic_version", noop)
    return processor, messages


def _task() -> SimpleNamespace:
    return SimpleNamespace(progress_data={}, name="", task_type="LIST_FROM_GRAND")


@pytest.mark.asyncio
async def test_warning_names_positions_ai_skipped(monkeypatch):
    """ИИ вернул одну позицию из трёх — про две остальные сказано номерами."""
    processor, messages = _processor(monkeypatch, [
        {"type": "Работа", "name": "Устройства промежуточные на количество лучей: 10",
         "unit": "шт", "quantity": 1},
    ])

    await processor._handle_list_from_grand_xlsx(_task(), _grand_xlsx())

    warning = next((m for m in messages if m.startswith("⚠")), "")
    assert "2 позиции" in warning
    assert "№3, №5" in warning


@pytest.mark.asyncio
async def test_no_warning_when_ai_returned_everything(monkeypatch):
    """Все позиции на месте — лишнего предупреждения задача не пишет."""
    processor, messages = _processor(monkeypatch, [
        {"type": "Работа", "name": "Устройства промежуточные на количество лучей: 10",
         "unit": "шт", "quantity": 1},
        {"type": "Материал", "name": "Контроллер Панель-2-ПРО (S3) исп.Л", "unit": "шт", "quantity": 1},
        {"type": "Материал", "name": "Извещатель ИП 212-141 исп.01", "unit": "шт", "quantity": 113},
    ])

    await processor._handle_list_from_grand_xlsx(_task(), _grand_xlsx())

    assert not any(m.startswith("⚠") for m in messages)
