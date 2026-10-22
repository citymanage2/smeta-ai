"""Строка материала в скачиваемых xlsx — синий курсив, текст прижат вправо.

Правило жило только в перечне: в смете, версии оптимизации, сравнении версий и
разделах сводной материал выглядел так же, как работа. В сводной не работала и
заливка работ — генератор сравнивал тип с «Работа», а раздел хранит строки
документа с типом "work".

Оформление не трогает значения: числа в ячейках проверены здесь же точно.
"""
import io
from types import SimpleNamespace

import openpyxl
import pytest

from app.utils.estimate_rows import canonical_type
from app.utils.xlsx_row_style import MATERIAL_FONT_COLOR

WORK_FILL = "EBF3FB"


def _book(data: bytes):
    return openpyxl.load_workbook(io.BytesIO(data))


def _blue_italic(cell) -> bool:
    color = cell.font.color.rgb if cell.font.color is not None else None
    return bool(cell.font.i) and isinstance(color, str) and color.endswith(MATERIAL_FONT_COLOR)


def _fill(cell):
    if cell.fill is None or cell.fill.fill_type != "solid":
        return None
    return str(cell.fill.start_color.rgb)[-6:]


def _row_of(ws, name: str, name_col: int) -> int:
    for row in range(1, ws.max_row + 1):
        if ws.cell(row=row, column=name_col).value == name:
            return row
    raise AssertionError(f"строка «{name}» не найдена")


# ── Тип строки в любом написании ────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("work", "work"), ("Работа", "work"), (" работы ", "work"),
    ("material", "material"), ("Материал", "material"), ("МАТЕРИАЛЫ", "material"),
    ("section", "section"), ("Раздел", "section"),
    (None, ""), ("", ""), ("Оборудование", "оборудование"),
])
def test_canonical_type(raw, expected):
    assert canonical_type(raw) == expected


# ── Разделы сводной ─────────────────────────────────────────────────────────

def _summary_sheet(rows):
    from app.utils.xlsx_summary import generate_summary_xlsx
    summary = SimpleNamespace(
        sections=[{"card_name": "Гостиница", "rows": rows}], overrides={},
    )
    return _book(generate_summary_xlsx(summary))["Гостиница"]


# Раздел — копия строк документа: тип "work"/"material".
DOC_ROWS = [
    {"type": "work", "name": "Вырубка деревьев", "unit": "шт",
     "qty": 303, "price_work": 3800, "price_material": None},
    {"type": "material", "name": "Рабочий", "unit": "чел/час",
     "qty": 606, "price_work": None, "price_material": 320},
]
# Старый снимок раздела — позиции ИИ: «Работа»/«Материал».
LEGACY_ROWS = [
    {"type": "Работа", "name": "Вырубка деревьев", "unit": "шт",
     "quantity": 303, "work_price": 3800, "material_price": None},
    {"type": "Материал", "name": "Рабочий", "unit": "чел/час",
     "quantity": 606, "work_price": None, "material_price": 320},
]


@pytest.mark.parametrize("rows", [DOC_ROWS, LEGACY_ROWS], ids=["doc", "legacy"])
def test_summary_section_styles(rows):
    ws = _summary_sheet(rows)
    work, material = 2, 3

    # Работа — голубая заливка, обычный шрифт.
    assert [_fill(ws.cell(row=work, column=c)) for c in range(1, 9)] == [WORK_FILL] * 8
    assert not any(ws.cell(row=work, column=c).font.i for c in range(1, 9))

    # Материал — синий курсив от наименования до стоимости, без заливки;
    # номер чёрный, как в перечне.
    assert not _blue_italic(ws.cell(row=material, column=1))
    assert all(_blue_italic(ws.cell(row=material, column=c)) for c in range(2, 9))
    assert [ws.cell(row=material, column=c).alignment.horizontal for c in (2, 3, 4)] == [
        "right", "right", "right",
    ]
    assert all(_fill(ws.cell(row=material, column=c)) is None for c in range(1, 9))

    # Значения те же: 303 × 3800, 606 × 320.
    assert [ws.cell(row=work, column=c).value for c in range(1, 9)] == [
        1, "Вырубка деревьев", "шт", 303, 3800, 1151400, None, None,
    ]
    assert [ws.cell(row=material, column=c).value for c in range(1, 9)] == [
        2, "Рабочий", "чел/час", 606, None, None, 320, 193920,
    ]
    assert ws.cell(row=material, column=8).number_format == "#,##0.00"


# ── Смета ───────────────────────────────────────────────────────────────────

def _estimate_sheet(items):
    from app.utils.xlsx_exporter import ESTIMATE_SHEET_TITLE, generate_estimate_xlsx
    data, _ = generate_estimate_xlsx(items, overhead_pct=0, transport_pct=0)
    return _book(data)[ESTIMATE_SHEET_TITLE]


ITEMS = [
    {"type": "Работа", "name": "Монтаж кабеля", "unit": "м", "quantity": 10,
     "work_price": 100, "material_price": None, "price_list_name": "Прайс", "notes": "п1"},
    {"type": "Материал", "name": "Кабель ВВГнг 3х2,5", "unit": "м", "quantity": 10,
     "work_price": None, "material_price": 33.5, "price_list_name": "ИИ", "notes": "п2"},
    # Позиция ИИ в нижнем регистре — тоже материал.
    {"type": "материал", "name": "Хомут", "unit": "шт", "quantity": 4,
     "work_price": None, "material_price": 5, "price_list_name": "", "notes": ""},
]


@pytest.mark.parametrize("with_source_no", [False, True])
def test_estimate_material_styles(with_source_no):
    items = [dict(i, source_no=str(n)) for n, i in enumerate(ITEMS, 1)] if with_source_no else ITEMS
    ws = _estimate_sheet(items)
    off = 1 if with_source_no else 0
    work = _row_of(ws, "Монтаж кабеля", 2 + off)

    assert all(ws.cell(row=work, column=c).font.b for c in range(1, 11 + off))
    assert not any(ws.cell(row=work, column=c).font.i for c in range(1, 11 + off))
    assert _fill(ws.cell(row=work, column=2 + off)) == WORK_FILL

    for name in ("Кабель ВВГнг 3х2,5", "Хомут"):
        row = _row_of(ws, name, 2 + off)
        # № в исходной смете и порядковый номер — чёрные.
        assert not any(_blue_italic(ws.cell(row=row, column=c)) for c in range(1, 2 + off))
        # Наименование … стоимость материалов — синий курсив.
        assert all(_blue_italic(ws.cell(row=row, column=c)) for c in range(2 + off, 9 + off))
        assert [ws.cell(row=row, column=c).alignment.horizontal
                for c in (2 + off, 3 + off, 4 + off)] == ["right", "right", "right"]
        # Источник цены и примечание — чёрные.
        assert not any(_blue_italic(ws.cell(row=row, column=c)) for c in (9 + off, 10 + off))
        assert _fill(ws.cell(row=row, column=2 + off)) is None

    cable = _row_of(ws, "Кабель ВВГнг 3х2,5", 2 + off)
    assert [ws.cell(row=cable, column=c).value for c in range(2 + off, 11 + off)] == [
        "Кабель ВВГнг 3х2,5", "м", 10, None, None, 33.5, 335, "ИИ", "п2",
    ]


# ── Версия оптимизации ──────────────────────────────────────────────────────

VERSION_ROWS = [
    {"id": "s1", "type": "section", "name": "Раздел 1"},
    {"id": "a", "num": 1, "type": "work", "name": "Монтаж кабеля", "unit": "м",
     "qty": 10, "price_work": 100.5, "price_material": None,
     "kp_ref": {"field": "price_work", "price": 100.5, "includes_materials": False}},
    {"id": "b", "num": 2, "type": "material", "name": "Кабель", "unit": "м",
     "qty": 10, "price_work": None, "price_material": 33.5},
]


def test_version_export_material_styles():
    from app.services.excel_service import generate_estimate_export
    from app.utils.kp_marks import KP_FILL_COLOR
    ws = _book(generate_estimate_export(
        rows=VERSION_ROWS, overhead_pct=0, transport_pct=0, contingency_pct=0,
        version_display_name="V1",
    ))["Смета"]
    section, work, material = 2, 3, 4

    assert ws.cell(row=section, column=3).font.b
    assert not ws.cell(row=section, column=3).font.i
    # Работа с ценой из КП — заливка КП осталась, курсива нет.
    assert _fill(ws.cell(row=work, column=3)) == KP_FILL_COLOR
    assert not any(ws.cell(row=work, column=c).font.i for c in range(1, 9))

    assert not _blue_italic(ws.cell(row=material, column=1))
    assert all(_blue_italic(ws.cell(row=material, column=c)) for c in range(2, 9))
    assert [ws.cell(row=material, column=c).alignment.horizontal for c in (3, 4, 5)] == [
        "right", "right", "right",
    ]
    # Рамка и кегль файла сохранились.
    assert ws.cell(row=material, column=3).border.left.style == "thin"
    assert ws.cell(row=material, column=3).font.sz == 11
    assert [ws.cell(row=material, column=c).value for c in range(1, 9)] == [
        2, "Материал", "Кабель", "м", 10, None, 33.5, 335,
    ]


def test_comparison_export_material_styles():
    from app.services.excel_service import generate_comparison_export
    versions = [
        {"id": vid, "version_display_name": vid, "rows": VERSION_ROWS,
         "overhead_pct": 0, "transport_pct": 0, "contingency_pct": 0}
        for vid in ("V0", "V1")
    ]
    ws = _book(generate_comparison_export(versions))["Сравнение"]
    material = _row_of(ws, "Кабель", 3)
    work = _row_of(ws, "Монтаж кабеля", 3)

    assert not _blue_italic(ws.cell(row=material, column=1))
    # Тип, наименование, ед. изм. и числа обеих версий (4 + 2 × 4 колонки).
    assert all(_blue_italic(ws.cell(row=material, column=c)) for c in range(2, 13))
    assert [ws.cell(row=material, column=c).alignment.horizontal for c in (3, 4)] == [
        "right", "right",
    ]
    assert not any(ws.cell(row=work, column=c).font.i for c in range(1, 13))


# ── Выгрузка-ведомость (конструктор) ────────────────────────────────────────

# Колонки и строки — как их собирает «Ведомость по сводной»
# (`SummaryEditorTabs.exportRows`): тип строки едет ключом `_kind`.
STATEMENT_COLUMNS = [
    {"key": "section_name", "label": "Раздел", "numeric": False},
    {"key": "num", "label": "№", "numeric": True},
    {"key": "name", "label": "Наименование", "numeric": False},
    {"key": "unit", "label": "Ед. изм.", "numeric": False},
    {"key": "qty", "label": "Кол-во", "numeric": True},
    {"key": "price_work", "label": "Цена работ", "numeric": True},
    {"key": "cost_work", "label": "Стоим. работ", "numeric": True},
    {"key": "price_material", "label": "Цена матер.", "numeric": True},
    {"key": "cost_material", "label": "Стоим. матер.", "numeric": True},
]
STATEMENT_ROWS = [
    {"_id": "c:1", "_kind": "work", "_section": "c", "section_name": "Гостиница",
     "num": 1, "name": "Вырубка деревьев", "unit": "шт", "qty": 303,
     "price_work": 3800, "cost_work": 1151400, "price_material": None, "cost_material": None},
    {"_id": "c:2", "_kind": "material", "_section": "c", "section_name": "Гостиница",
     "num": 2, "name": "Рабочий", "unit": "чел/час", "qty": 606,
     "price_work": None, "cost_work": None, "price_material": 320, "cost_material": 193920},
]


def test_statement_material_styles():
    from app.utils.xlsx_statement import generate_statement_xlsx
    ws = _book(generate_statement_xlsx(
        STATEMENT_COLUMNS, STATEMENT_ROWS, title="Ведомость по сводной",
    )).worksheets[0]
    work = _row_of(ws, "Вырубка деревьев", 3)
    material = _row_of(ws, "Рабочий", 3)

    assert not any(ws.cell(row=work, column=c).font.i for c in range(1, 10))
    # Раздел и № — чёрные; наименование … стоимость материалов — синий курсив.
    assert not any(_blue_italic(ws.cell(row=material, column=c)) for c in (1, 2))
    assert all(_blue_italic(ws.cell(row=material, column=c)) for c in range(3, 10))
    assert [ws.cell(row=material, column=c).alignment.horizontal for c in (3, 4, 5)] == [
        "right", "right", "right",
    ]
    # Рамка ведомости не пострадала.
    assert ws.cell(row=material, column=3).border.left.style == "thin"

    # № — целым числом, а не «1,00»; деньги — прежним форматом.
    assert ws.cell(row=work, column=2).value == 1
    assert isinstance(ws.cell(row=work, column=2).value, int)
    assert ws.cell(row=work, column=2).number_format == "General"
    assert [ws.cell(row=material, column=c).value for c in range(1, 10)] == [
        "Гостиница", 2, "Рабочий", "чел/час", 606, None, None, 320, 193920,
    ]
    assert ws.cell(row=material, column=9).number_format == "#,##0.00"

    # Итог: № и цены не складываются, стоимости — да.
    total = material + 1
    assert ws.cell(row=total, column=1).value == "ИТОГО"
    assert ws.cell(row=total, column=2).value is None
    assert ws.cell(row=total, column=7).value == 1151400
    assert ws.cell(row=total, column=9).value == 193920


def test_statement_material_label_based_columns():
    """Документ с колонками из файла заказчика: ключи свои, решают подписи."""
    from app.utils.xlsx_statement import generate_statement_xlsx
    columns = [
        {"key": "c0", "label": "№ п/п", "numeric": False},
        {"key": "c1", "label": "Наименование работ и затрат", "numeric": False},
        {"key": "c2", "label": "Примечание", "numeric": False},
    ]
    rows = [{"_id": "1", "_kind": "material", "c0": "1", "c1": "Кабель", "c2": "из КП"}]
    ws = _book(generate_statement_xlsx(columns, rows, title="")).worksheets[0]
    row = _row_of(ws, "Кабель", 2)

    assert not _blue_italic(ws.cell(row=row, column=1))
    assert _blue_italic(ws.cell(row=row, column=2))
    assert ws.cell(row=row, column=2).alignment.horizontal == "right"
    assert not _blue_italic(ws.cell(row=row, column=3))


# ── Перечень: правило прежнее, цвет общий ───────────────────────────────────

def test_perechen_material_styles_unchanged():
    from app.services.excel_service import generate_list
    ws = _book(generate_list([
        {"type": "Работа", "name": "Монтаж кабеля", "unit": "м", "quantity": 10},
        {"type": "Материал", "name": "Кабель", "unit": "м", "quantity": 10},
    ])).worksheets[0]
    material = _row_of(ws, "Кабель", 3)
    work = _row_of(ws, "Монтаж кабеля", 3)

    assert all(_blue_italic(ws.cell(row=material, column=c)) for c in (2, 3, 4, 5))
    assert ws.cell(row=material, column=3).font.name == "Arial"
    assert ws.cell(row=material, column=3).alignment.horizontal == "right"
    assert ws.cell(row=work, column=3).alignment.horizontal == "left"
    assert not any(ws.cell(row=work, column=c).font.i for c in range(1, 7))
