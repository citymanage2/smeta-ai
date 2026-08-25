"""Оборванный ответ на стадии перечня дробит чанк, а не роняет задачу.

Ответ по перечню длиннее входа (каждая расценка разворачивается в блок
«работа + её материалы»), поэтому плотный чанк упирается в лимит и приходит
обрезанным. Раньше это валило всю стадию сообщением «Ответ слишком большой,
разбейте выполнение на подэтапы»; повтор упирался в тот же лимит.

План: plans/2026-08-26-oborvannyj-otvet-perechnya.md
"""
import io
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import openpyxl
import pytest

sys.modules.setdefault("fitz", MagicMock())

from app.services.claude_service import ResponseTruncatedError  # noqa: E402
from app.services.task_processor import TaskProcessor  # noqa: E402
from app.utils.file_parser import split_chunk_in_half  # noqa: E402
from app.utils.pdf_ocr_extractor import split_pdf_chunk  # noqa: E402


# --- деление чанка строк -------------------------------------------------


def _work(name: str) -> dict:
    """Строка-работа: в гранд-смете у неё нет ни единицы, ни объёма в этих колонках."""
    return {"name": name, "unit": "", "quantity": None, "is_section": False}


def _material(name: str) -> dict:
    return {"name": name, "unit": "м2", "quantity": 10, "is_section": False}


def test_split_keeps_work_with_its_materials():
    """Граница проходит по началу работы, а не посреди её материалов."""
    rows = [
        _work("Работа 1"), _material("Материал 1.1"), _material("Материал 1.2"),
        _work("Работа 2"), _material("Материал 2.1"), _material("Материал 2.2"),
    ]

    left, right = split_chunk_in_half(rows)

    assert [r["name"] for r in left] == ["Работа 1", "Материал 1.1", "Материал 1.2"]
    assert [r["name"] for r in right] == ["Работа 2", "Материал 2.1", "Материал 2.2"]


def test_split_falls_back_to_middle_without_boundary():
    """Границы работы нет — режем по середине, лишь бы обе половины были короче."""
    rows = [_material(f"Материал {i}") for i in range(6)]

    left, right = split_chunk_in_half(rows)

    assert len(left) == 3 and len(right) == 3


def test_split_always_shrinks_both_halves():
    """Деление обязано сходиться: пустых половин быть не может."""
    for size in range(2, 30):
        rows = [_work(f"Работа {i}") for i in range(size)]
        left, right = split_chunk_in_half(rows)
        assert 0 < len(left) < size
        assert 0 < len(right) < size
        assert len(left) + len(right) == size


def test_split_bottom_is_single_row():
    """Одна строка — делить нечего."""
    assert split_chunk_in_half([_work("Работа 1")]) is None
    assert split_chunk_in_half([]) is None


# --- деление текстового чанка PDF ---------------------------------------


def _pdf_chunk(pages: int) -> str:
    """Чанк из N страниц: внутри страницы есть пустые строки — как после OCR."""
    parts = [
        f"--- Страница {n} (метод: text) ---\nПозиция {n}.1\n\nПозиция {n}.2"
        for n in range(1, pages + 1)
    ]
    return "\n\n".join(parts)


def test_pdf_split_cuts_on_page_boundary():
    """Режем по заголовку страницы, а не по первой попавшейся пустой строке."""
    left, right = split_pdf_chunk(_pdf_chunk(4))

    assert left.count("--- Страница ") == 2
    assert right.count("--- Страница ") == 2
    assert left.startswith("--- Страница 1")
    assert right.startswith("--- Страница 3")
    # Текст страницы не разорван: обе её позиции остались вместе.
    assert "Позиция 1.1" in left and "Позиция 1.2" in left


def test_pdf_split_bottom_is_single_page():
    """Одна страница — делить нечего, даже если внутри есть пустые строки."""
    assert split_pdf_chunk(_pdf_chunk(1)) is None


# --- стадия перечня целиком ----------------------------------------------


def _grand_xlsx() -> bytes:
    """Четыре позиции ЛСР с номерами 1–4."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ЛОКАЛЬНЫЙ СМЕТНЫЙ РАСЧЕТ (СМЕТА) № 1"])
    ws.append(["№ п/п", "Обоснование", "Наименование работ и затрат",
               "Единица измерения", "Количество"])
    ws.append([1, "ФЕР10-01-001", "Устройство перегородок из ГКЛ", "м2", 100])
    ws.append([2, "ТЦ_01", "Профиль направляющий ПН-2", "м", 120])
    ws.append([3, "ФЕР10-01-002", "Облицовка стен ГКЛ", "м2", 80])
    ws.append([4, "ТЦ_02", "Лист гипсокартонный 12,5 мм", "м2", 88])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _processor(monkeypatch, answer):
    """Обработчик с подменённым ИИ: `answer(prompt_text)` → dict или исключение."""
    processor = TaskProcessor("tid-truncated", db=MagicMock())
    messages: list = []
    saved: dict = {}

    async def fake_progress(message: str) -> None:
        messages.append(message)

    async def fake_claude(msgs, *args, **kwargs) -> dict:
        return answer(msgs[0]["content"])

    async def noop(*args, **kwargs) -> None:
        return None

    async def fake_version(excel_data, task_type, items) -> None:
        saved["items"] = items

    monkeypatch.setattr(processor, "update_progress", fake_progress)
    monkeypatch.setattr(processor, "_call_claude_json_with_retry", fake_claude)
    monkeypatch.setattr(processor, "_check_cancelled", noop)
    monkeypatch.setattr(processor, "_save_progress_data", noop)
    monkeypatch.setattr(processor, "save_result", noop)
    monkeypatch.setattr(processor, "_create_initial_generic_version", fake_version)
    return processor, messages, saved


def _task(task_type: str = "LIST_FROM_GRAND") -> SimpleNamespace:
    return SimpleNamespace(progress_data={}, name="", task_type=task_type)


@pytest.mark.asyncio
async def test_truncated_chunk_is_split_and_stage_completes(monkeypatch):
    """Целый чанк не помещается — считаем половины, задача доходит до конца."""
    calls: list = []

    def answer(prompt: str) -> dict:
        calls.append(prompt)
        # Первый запрос — весь чанк из четырёх позиций: ответ не поместился.
        if "Устройство перегородок" in prompt and "Облицовка стен" in prompt:
            raise ResponseTruncatedError("Ответ слишком большой")
        items = []
        if "Устройство перегородок" in prompt:
            items = [
                {"type": "Работа", "name": "Устройство перегородок из ГКЛ",
                 "unit": "м2", "quantity": 100},
                {"type": "Материал", "name": "Профиль направляющий ПН-2",
                 "unit": "м", "quantity": 120},
            ]
        elif "Облицовка стен" in prompt:
            items = [
                {"type": "Работа", "name": "Облицовка стен ГКЛ", "unit": "м2", "quantity": 80},
                {"type": "Материал", "name": "Лист гипсокартонный 12,5 мм",
                 "unit": "м2", "quantity": 88},
            ]
        return {"items": items}

    processor, messages, saved = _processor(monkeypatch, answer)

    await processor._handle_list_from_grand_xlsx(_task(), _grand_xlsx())

    # Оборванный чанк + две половины.
    assert len(calls) == 3
    names = [it["name"] for it in saved["items"]]
    assert names == [
        "Устройство перегородок из ГКЛ",
        "Профиль направляющий ПН-2",
        "Облицовка стен ГКЛ",
        "Лист гипсокартонный 12,5 мм",
    ]
    # Номера позиций ЛСР проставлены по своей половине, не перепутаны.
    assert [it.get("source_no") for it in saved["items"]] == ["1", "2", "3", "4"]
    assert not [m for m in messages if m.startswith("⚠")]


@pytest.mark.asyncio
async def test_bottom_of_recursion_reports_lost_positions(monkeypatch):
    """Даже одна строка не поместилась — позиция не выдумана, её номер назван."""
    def answer(prompt: str) -> dict:
        # Позиция №1 не помещается в лимит ни в каком составе чанка —
        # рекурсия дойдёт до неё одной и упрётся в дно.
        if "Устройство перегородок" in prompt:
            raise ResponseTruncatedError("Ответ слишком большой")
        items = []
        if "Профиль направляющий" in prompt:
            items.append({"type": "Материал", "name": "Профиль направляющий ПН-2",
                          "unit": "м", "quantity": 120})
        if "Облицовка стен" in prompt:
            items.append({"type": "Работа", "name": "Облицовка стен ГКЛ",
                          "unit": "м2", "quantity": 80})
        if "Лист гипсокартонный" in prompt:
            items.append({"type": "Материал", "name": "Лист гипсокартонный 12,5 мм",
                          "unit": "м2", "quantity": 88})
        return {"items": items}

    processor, messages, saved = _processor(monkeypatch, answer)

    await processor._handle_list_from_grand_xlsx(_task(), _grand_xlsx())

    names = [it["name"] for it in saved["items"]]
    assert "Устройство перегородок из ГКЛ" not in names
    assert "Облицовка стен ГКЛ" in names

    warning = next((m for m in messages if m.startswith("⚠")), "")
    assert "1 позицию" in warning
    assert "№1" in warning


@pytest.mark.asyncio
async def test_pdf_truncated_chunk_is_split(monkeypatch):
    """PDF: чанк не поместился — считаем его постранично."""
    calls: list = []

    def answer(prompt: str) -> dict:
        calls.append(prompt)
        if "Страница 1" in prompt and "Страница 2" in prompt:
            raise ResponseTruncatedError("Ответ слишком большой")
        page = "1" if "Страница 1" in prompt else "2"
        return {"items": [
            {"type": "Работа", "name": f"Работа со страницы {page}",
             "unit": "м2", "quantity": 5},
        ]}

    processor, messages, saved = _processor(monkeypatch, answer)
    monkeypatch.setattr(
        "app.services.task_processor.chunk_pdf_pages", lambda pages: [_pdf_chunk(2)]
    )

    task = _task()
    task.progress_data = {"ocr_pages": [
        {"page": 1, "text": "x" * 100, "method": "text"},
        {"page": 2, "text": "y" * 100, "method": "text"},
    ]}

    await processor._handle_list_from_grand_pdf(task, b"%PDF-fake")

    assert len(calls) == 3
    assert [it["name"] for it in saved["items"]] == [
        "Работа со страницы 1",
        "Работа со страницы 2",
    ]
