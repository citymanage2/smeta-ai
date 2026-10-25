"""Tests for xlsx_optimizer utility."""
import io

import openpyxl
import pytest

from app.config import settings
from app.utils.xlsx_exporter import generate_estimate_xlsx
from app.utils.xlsx_optimizer import (
    parse_estimate_xlsx,
    get_top_items,
    generate_optimized_xlsx,
)


@pytest.fixture(autouse=True)
def vat_22(monkeypatch):
    """Ставка НДС — настройка окружения; числа ниже посчитаны при 22 %."""
    monkeypatch.setattr(settings, "VAT_RATE", 0.22)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_smeta_xlsx(items: list[dict]) -> bytes:
    """Смета в том виде, в каком её кладёт в слот «estimate» расчёт сметы.

    Оптимизация разбирает именно этот файл (`POST /tasks/{id}/optimize/analyze`
    читает слот «estimate»). Колонки «Тип» в нём нет — тип определяется по
    наименованию. Накладные и транспортные обнулены: они идут строками итогов,
    а не в цену позиции.
    """
    data, _ = generate_estimate_xlsx(
        [
            {"type": it.get("type", "Материал"), "name": it["name"],
             "unit": it.get("unit", "шт"), "quantity": it.get("quantity", 1),
             "work_price": it.get("work_price"), "material_price": it.get("material_price")}
            for it in items
        ],
        overhead_pct=0, transport_pct=0,
    )
    return data


def _make_smeta_items():
    """Return 5 test items with varying total costs."""
    return [
        {"name": "Кирпич М150", "type": "Материал", "unit": "шт", "quantity": 1000, "material_price": 10.0},   # с НДС 12 200
        {"name": "Монтаж трубы", "type": "Работа", "unit": "м", "quantity": 50, "work_price": 500.0},           # с НДС 30 500
        {"name": "Цемент М400", "type": "Материал", "unit": "кг", "quantity": 200, "material_price": 20.0},    # с НДС 4 880
        {"name": "Устройство стяжки", "type": "Работа", "unit": "м2", "quantity": 100, "work_price": 300.0},   # с НДС 36 600
        {"name": "Гвозди 100мм", "type": "Материал", "unit": "кг", "quantity": 10, "material_price": 50.0},   # с НДС 610
    ]
    # По убыванию: стяжка 36 600, монтаж 30 500, кирпич 12 200, цемент 4 880, гвозди 610.
    # Всего 84 790; 70 % = 59 353 → стяжка + монтаж = 67 100 — первые две позиции.


# ---------------------------------------------------------------------------
# parse_estimate_xlsx tests
# ---------------------------------------------------------------------------

def test_parse_estimate_xlsx_returns_items():
    """Позиции сметы: цена за единицу без НДС и с НДС, стоимость с НДС."""
    items = _make_smeta_items()[:3]
    file_bytes = _make_smeta_xlsx(items)
    result = parse_estimate_xlsx(file_bytes)
    assert [
        (it["name"], it["type"], it["unit"], it["quantity"],
         it["price_excl_vat"], it["price_incl_vat"], it["total"])
        for it in result
    ] == [
        ("Кирпич М150", "material", "шт", 1000, 10.0, 12.2, 12200.0),
        ("Монтаж трубы", "work", "м", 50, 500.0, 610.0, 30500.0),
        ("Цемент М400", "material", "кг", 200, 20.0, 24.4, 4880.0),
    ]
    assert [it["row_index"] for it in result] == [2, 3, 4]


def test_parse_estimate_xlsx_skips_empty_rows():
    """Rows with no name value are skipped."""
    wb = openpyxl.Workbook()
    ws = wb.active
    headers = ["№", "Тип", "Наименование", "Ед. изм.", "Кол-во", "Цена работы (за ед.)", "Цена материала (за ед.)",
               "Стоимость работ", "Стоимость материалов", "Итого без НДС", "НДС (20%)", "Итого с НДС",
               "Наименование в прайсе", "Источники", "Примечание"]
    for col, h in enumerate(headers, start=1):
        ws.cell(row=1, column=col, value=h)
    # Row 2: valid item
    ws.cell(row=2, column=2, value="Материал")
    ws.cell(row=2, column=3, value="Кирпич М150")
    ws.cell(row=2, column=5, value=100)
    ws.cell(row=2, column=7, value=10.0)
    ws.cell(row=2, column=12, value=1200.0)
    # Row 3: empty name (ИТОГО row)
    ws.cell(row=3, column=1, value="ИТОГО")
    buf = io.BytesIO()
    wb.save(buf)
    result = parse_estimate_xlsx(buf.getvalue())
    assert len(result) == 1
    assert result[0]["name"] == "Кирпич М150"


# ---------------------------------------------------------------------------
# get_top_items tests
# ---------------------------------------------------------------------------

def test_get_top_items_covers_threshold():
    """Самые дорогие позиции, пока их сумма не перекроет 70 % сметы."""
    parsed = parse_estimate_xlsx(_make_smeta_xlsx(_make_smeta_items()))
    selected = get_top_items(parsed, categories=["work", "material"], threshold=0.7)
    assert [it["name"] for it in selected] == ["Устройство стяжки", "Монтаж трубы"]


def test_get_top_items_filters_categories():
    """Только материалы, и порог — от суммы материалов, а не всей сметы.

    Материалы: 12 200 + 4 880 + 610 = 17 690; 70 % = 12 383 → кирпич и цемент.
    """
    parsed = parse_estimate_xlsx(_make_smeta_xlsx(_make_smeta_items()))
    selected = get_top_items(parsed, categories=["material"], threshold=0.7)
    assert [it["name"] for it in selected] == ["Кирпич М150", "Цемент М400"]


# ---------------------------------------------------------------------------
# generate_optimized_xlsx tests
# ---------------------------------------------------------------------------

def _make_optimization_results(items_parsed: list[dict]) -> list[dict]:
    """Build mock optimization_results: first item found, rest not found."""
    results = []
    for i, it in enumerate(items_parsed):
        if i == 0:
            results.append({
                "row_index": it["row_index"],
                "name": it["name"],
                "original_price": it["price_incl_vat"],
                "new_price": it["price_incl_vat"] * 0.8,
                "source": "https://example.com/price",
                "savings_abs": it["price_incl_vat"] * 0.2,
                "savings_pct": 20.0,
                "has_vat": True,
            })
        else:
            results.append({
                "row_index": it["row_index"],
                "name": it["name"],
                "original_price": it["price_incl_vat"],
                "new_price": None,
                "source": "Не найдено",
                "savings_abs": None,
                "savings_pct": None,
                "has_vat": True,
            })
    return results


def _column(ws, header: str) -> int:
    for col in range(1, ws.max_column + 1):
        if ws.cell(row=1, column=col).value == header:
            return col
    raise AssertionError(f"колонка «{header}» не найдена")


def test_generate_optimized_xlsx_adds_columns():
    """Найденный аналог: новая цена и стоимость в строке позиции; не найден — стоимости нет.

    Кирпич: 12,2 × 0,8 = 9,76 за шт, × 1000 шт = 9 760.
    """
    items = _make_smeta_items()[:3]
    original_bytes = _make_smeta_xlsx(items)
    parsed = parse_estimate_xlsx(original_bytes)
    opt_results = _make_optimization_results(parsed)
    result_bytes = generate_optimized_xlsx(original_bytes, opt_results)
    ws = openpyxl.load_workbook(io.BytesIO(result_bytes)).active

    price, cost, source = (_column(ws, h) for h in ("Цена сниженная", "Стоимость сниженная", "Источник"))
    brick, pipe = 2, 3
    assert ws.cell(row=brick, column=price).value == 9.76
    assert ws.cell(row=brick, column=cost).value == 9760.0
    assert ws.cell(row=brick, column=source).value == "https://example.com/price"
    assert not isinstance(ws.cell(row=pipe, column=price).value, (int, float))
    assert ws.cell(row=pipe, column=cost).value is None
    # Исходные колонки не тронуты: наименование, кол-во, цена материала.
    assert [ws.cell(row=brick, column=c).value for c in (2, 4, 7)] == ["Кирпич М150", 1000, 10]


def test_generate_optimized_xlsx_has_comparison_sheet():
    """Лист «Сравнение»: было / стало / экономия по позициям и итог экономии.

    Экономия 2,44 ₽ на единице кирпича при исходных ценах 12,2 + 610 = 622,2 —
    это 0,39 %.
    """
    items = _make_smeta_items()[:2]
    original_bytes = _make_smeta_xlsx(items)
    parsed = parse_estimate_xlsx(original_bytes)
    opt_results = _make_optimization_results(parsed)
    result_bytes = generate_optimized_xlsx(original_bytes, opt_results)
    ws = openpyxl.load_workbook(io.BytesIO(result_bytes))["Сравнение"]

    rows = list(ws.iter_rows(min_row=2, values_only=True))
    brick, pipe, total = rows
    assert brick == ("Кирпич М150", 12.2, 9.76, 2.44, 20.0, "https://example.com/price")
    assert (pipe[0], pipe[1], pipe[3], pipe[4]) == ("Монтаж трубы", 610.0, None, None)
    assert (total[3], total[4]) == (2.44, 0.39)
