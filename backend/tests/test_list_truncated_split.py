"""Оборванный ответ на стадии перечня дробит чанк, а не роняет задачу.

Ответ по перечню длиннее входа (каждая расценка разворачивается в блок
«работа + её материалы»), поэтому плотный чанк упирается в лимит и приходит
обрезанным. Раньше это валило всю стадию сообщением «Ответ слишком большой,
разбейте выполнение на подэтапы»; повтор упирался в тот же лимит.

План: plans/2026-08-26-oborvannyj-otvet-perechnya.md
"""
import io
import re

import openpyxl
from sqlalchemy import select

from app.models.estimate_version import EstimateVersion
from app.utils.file_parser import split_chunk_in_half
from app.utils.pdf_ocr_extractor import split_pdf_chunk
from app.utils.source_numbers import SOURCE_NO_HEADER
from tests.helpers.anthropic_api import claude_message, prompt_text

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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
#
# Прогон настоящий, на тестовой БД; подменён только ИИ. Перечень читается из
# документа задачи (версия V0 — то, что видит редактор), предупреждения — из
# хода выполнения (`progress_log`).


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


TRUNCATED = claude_message({"items": []}, stop_reason="max_tokens")


async def _list_rows(processor_env, task) -> list[tuple[str, str]]:
    """Строки перечня в документе задачи: (№ в исходной смете, наименование)."""
    task_id = str((await processor_env.reload(task)).id)
    version = (await processor_env.db.execute(
        select(EstimateVersion).where(
            EstimateVersion.task_id == task_id, EstimateVersion.file_slot == "result",
        )
    )).scalar_one()
    return [
        (str(row["cells"].get(SOURCE_NO_HEADER, "")), row["cells"]["Наименование"])
        for row in version.rows
    ]


def _warnings(task) -> list[str]:
    return [line for line in task.progress_log or [] if line.startswith("⚠")]


async def _run_grand_xlsx(processor_env, claude_api, answer):
    """Перечень из гранд-сметы (xlsx); ИИ отвечает `answer(prompt) -> ответ`."""
    ai = claude_api(lambda kwargs: answer(prompt_text(kwargs)), repeat=True)
    task = await processor_env.task(
        "LIST_FROM_GRAND", input_files=[{"name": "ЛСР.xlsx", "mime_type": XLSX_MIME}],
    )
    await processor_env.input_file(task, "ЛСР.xlsx", XLSX_MIME, _grand_xlsx())
    return await processor_env.run(task), ai


async def test_truncated_chunk_is_split_and_stage_completes(processor_env, claude_api):
    """Целый чанк не помещается — считаем половины, задача доходит до конца."""
    def answer(prompt: str):
        # Первый запрос — весь чанк из четырёх позиций: ответ не поместился.
        if "Устройство перегородок" in prompt and "Облицовка стен" in prompt:
            return TRUNCATED
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

    task, ai = await _run_grand_xlsx(processor_env, claude_api, answer)

    assert task.status == "completed"
    # Оборванный чанк + две половины.
    assert len(ai.calls) == 3
    # Номера позиций ЛСР проставлены по своей половине, не перепутаны.
    assert await _list_rows(processor_env, task) == [
        ("1", "Устройство перегородок из ГКЛ"),
        ("2", "Профиль направляющий ПН-2"),
        ("3", "Облицовка стен ГКЛ"),
        ("4", "Лист гипсокартонный 12,5 мм"),
    ]
    assert _warnings(task) == []


async def test_bottom_of_recursion_reports_lost_positions(processor_env, claude_api):
    """Даже одна строка не поместилась — позиция не выдумана, её номер назван."""
    def answer(prompt: str):
        # Позиция №1 не помещается в лимит ни в каком составе чанка —
        # рекурсия дойдёт до неё одной и упрётся в дно.
        if "Устройство перегородок" in prompt:
            return TRUNCATED
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

    task, _ = await _run_grand_xlsx(processor_env, claude_api, answer)

    assert task.status == "completed"
    assert await _list_rows(processor_env, task) == [
        ("2", "Профиль направляющий ПН-2"),
        ("3", "Облицовка стен ГКЛ"),
        ("4", "Лист гипсокартонный 12,5 мм"),
    ]
    (warning,) = _warnings(task)
    assert re.findall(r"№(\d+)", warning) == ["1"]


async def test_pdf_truncated_chunk_is_split(processor_env, claude_api):
    """PDF: чанк не поместился — считаем его постранично."""
    def answer(prompt: str):
        if "Страница 1" in prompt and "Страница 2" in prompt:
            return TRUNCATED
        page = "1" if "Страница 1" in prompt else "2"
        return {"items": [
            {"type": "Работа", "name": f"Работа со страницы {page}",
             "unit": "м2", "quantity": 5},
        ]}

    ai = claude_api(lambda kwargs: answer(prompt_text(kwargs)), repeat=True)
    # Текст страниц уже распознан (чекпоинт OCR): обе страницы — один чанк.
    task = await processor_env.task(
        "LIST_FROM_GRAND",
        input_files=[{"name": "ЛСР.pdf", "mime_type": "application/pdf"}],
        progress_data={"ocr_pages": [
            {"page": 1, "text": "Позиции первой страницы сметы " * 4, "method": "embedded"},
            {"page": 2, "text": "Позиции второй страницы сметы " * 4, "method": "embedded"},
        ]},
    )
    await processor_env.input_file(task, "ЛСР.pdf", "application/pdf", b"%PDF-1.4 fake")

    task = await processor_env.run(task)

    assert task.status == "completed"
    assert len(ai.calls) == 3
    assert [name for _, name in await _list_rows(processor_env, task)] == [
        "Работа со страницы 1",
        "Работа со страницы 2",
    ]
