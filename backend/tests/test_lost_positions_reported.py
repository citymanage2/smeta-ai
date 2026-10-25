"""Задача перечня говорит вслух, какие позиции ЛСР не вернул ИИ.

Проверка не самого сопоставления (оно в test_lost_positions_warning.py), а
связки: обработчик перечня из гранд-сметы сверяет ответ модели со строками
файла и пишет предупреждение в ход выполнения задачи.

Прогон настоящий, на тестовой БД; подменён только ИИ. Предупреждение читается
из хода выполнения (`progress_log`) — там его видит пользователь.

План: plans/2026-08-14-propusk-pozicij-iz-grand-smety.md, Фаза 3.
"""
import io
import re

import openpyxl

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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


async def _run(processor_env, claude_api, ai_items: list) -> list[str]:
    """Перечень из гранд-сметы, ИИ отвечает `ai_items`; вернуть предупреждения задачи."""
    claude_api({"items": ai_items})
    task = await processor_env.task(
        "LIST_FROM_GRAND", input_files=[{"name": "ЛСР.xlsx", "mime_type": XLSX_MIME}],
    )
    await processor_env.input_file(task, "ЛСР.xlsx", XLSX_MIME, _grand_xlsx())

    task = await processor_env.run(task)

    assert task.status == "completed"
    return [line for line in task.progress_log or [] if line.startswith("⚠")]


async def test_warning_names_positions_ai_skipped(processor_env, claude_api):
    """ИИ вернул одну позицию из трёх — про две остальные сказано номерами."""
    (warning,) = await _run(processor_env, claude_api, [
        {"type": "Работа", "name": "Устройства промежуточные на количество лучей: 10",
         "unit": "шт", "quantity": 1},
    ])

    assert re.findall(r"№(\d+)", warning) == ["3", "5"]


async def test_no_warning_when_ai_returned_everything(processor_env, claude_api):
    """Все позиции на месте — лишнего предупреждения задача не пишет."""
    warnings = await _run(processor_env, claude_api, [
        {"type": "Работа", "name": "Устройства промежуточные на количество лучей: 10",
         "unit": "шт", "quantity": 1},
        {"type": "Материал", "name": "Контроллер Панель-2-ПРО (S3) исп.Л", "unit": "шт", "quantity": 1},
        {"type": "Материал", "name": "Извещатель ИП 212-141 исп.01", "unit": "шт", "quantity": 113},
    ])

    assert warnings == []
