"""Колонка «№ в исходной смете» при разборе xlsx сметы.

Фаза 8а плана `plans/2026-09-14-zapros-kp.md`, проблема 32: заголовок
«№ в исходной смете» содержит «№», и разбор принимал его за «№ п/п». Номер
строки сметы тогда брался из чужой колонки, а настоящий «№ п/п» терялся.
Колонка узнаётся по общему заголовку `source_numbers.SOURCE_NO_HEADER` раньше
номера строки и едет полем `source_no`.
"""
import io

import openpyxl

from app.services.estimate_parser import parse_estimate_excel
from app.utils.source_numbers import SOURCE_NO_HEADER


def _xlsx(header: list, rows: list) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_source_no_column_is_not_taken_as_row_number():
    data = _xlsx(
        [SOURCE_NO_HEADER, "№ п/п", "Тип", "Наименование", "Ед. изм.", "Кол-во",
         "Цена работ", "Цена материалов"],
        [
            [12, 1, "Работа", "Кладка стен", "м2", 4, 1000, None],
            ["1.1", 2, "Материал", "Кирпич", "шт", 10, None, 500],
            [None, 3, "Работа", "Штукатурка", "м2", 5, 300, None],
        ],
    )
    rows = parse_estimate_excel(data)

    assert [r["name"] for r in rows] == ["Кладка стен", "Кирпич", "Штукатурка"]
    assert [r["num"] for r in rows] == [1, 2, 3]
    assert [r["source_no"] for r in rows] == ["12", "1.1", None]
    # Остальные колонки не съехали
    assert rows[0]["qty"] == 4 and rows[0]["price_work"] == 1000
    assert rows[1]["unit"] == "шт" and rows[1]["price_material"] == 500


def test_source_no_column_after_row_number():
    data = _xlsx(
        ["№ п/п", SOURCE_NO_HEADER, "Наименование", "Ед. изм.", "Кол-во", "Цена работ"],
        [[7, 3, "Кладка стен", "м2", 4, 1000]],
    )
    rows = parse_estimate_excel(data)

    assert rows[0]["num"] == 7
    assert rows[0]["source_no"] == "3"


def test_file_without_source_no_column_looks_as_before():
    data = _xlsx(
        ["№ п/п", "Наименование", "Ед. изм.", "Кол-во", "Цена работ"],
        [[5, "Кладка стен", "м2", 4, 1000]],
    )
    rows = parse_estimate_excel(data)

    assert rows[0]["num"] == 5
    assert "source_no" not in rows[0]
