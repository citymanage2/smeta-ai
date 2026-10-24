import io
import pytest
from decimal import Decimal
from typing import List
import openpyxl

from app.utils.xlsx_cost_parser import extract_total_cost


def _make_xlsx(rows: List[List]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_extract_total_cost_finds_итого():
    data = _make_xlsx([
        ["Работа", "Ед", "Кол", "Цена"],
        ["Копать ямы", "м3", 10, 5000],
        ["Итого", "", "", 50000],
    ])
    assert extract_total_cost(data) == Decimal("50000")


def test_extract_total_cost_finds_всего():
    data = _make_xlsx([
        ["Наименование", "Сумма"],
        ["Работы", 100000],
        ["Всего", 100000],
    ])
    assert extract_total_cost(data) == Decimal("100000")


def test_extract_total_cost_case_insensitive():
    data = _make_xlsx([
        ["  ИТОГО  ", "", 999.99],
    ])
    assert extract_total_cost(data) == Decimal("999.99")


def test_extract_total_cost_multiple_rows_returns_last():
    data = _make_xlsx([
        ["итого", "", 1000],
        ["Другие работы", "", 500],
        ["итого", "", 2000],
    ])
    assert extract_total_cost(data) == Decimal("2000")


def test_extract_total_cost_no_number_in_row_returns_none():
    data = _make_xlsx([
        ["итого", "нет числа", "—"],
    ])
    assert extract_total_cost(data) is None


def test_extract_total_cost_no_matching_row_returns_none():
    data = _make_xlsx([
        ["Работа", "Ед", "Цена"],
        ["Копать ямы", "м3", 5000],
    ])
    assert extract_total_cost(data) is None


def test_extract_total_cost_damaged_file_returns_none():
    assert extract_total_cost(b"not an xlsx file at all") is None
