"""Материал не должен превращаться в заголовок раздела.

Было: `_SECTION_HEADER` считал заголовком раздела любую строку, начинающуюся со
слова «блок», «узел», «часть» или «отдел». Позиция ЛСР «Блок дверной деревянный
внутренний распашной глухой…» помечалась `is_section=True`, уходила в Claude
строкой «=== Блок дверной… ===» — без единицы измерения и объёма, — а промпт
перечня прямо велит заголовки разделов пропускать. Материал пропадал из
перечня, а следующий за ним «Комплект монтажный» оставался: отсюда жалоба
«материалы пропускаются через один».

Стало: разделом считаются только «раздел / подраздел / глава», и только если у
строки нет ни единицы измерения, ни объёма.
"""
import io

import openpyxl

from app.utils.file_parser import parse_xlsx_grand, rows_to_text


def _lsr_xlsx() -> bytes:
    """Фрагмент ЛСР в раскладке ГРАНД-Сметы 2026: работа, затем её материалы."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ЛОКАЛЬНЫЙ СМЕТНЫЙ РАСЧЕТ (СМЕТА) № 1"])
    ws.append(["№ п/п", "Обоснование", "Наименование работ и затрат", "Единица измерения", "Количество"])
    ws.append(["Раздел 1. Кабинет №328"])
    ws.append([4, "ГЭСН10-01-039-01", "Установка блоков в наружных и внутренних дверных проемах", "100 м2", 0.018])
    ws.append([5, "ФСБЦ-11.2.02.01-1114", "Блок дверной деревянный внутренний распашной глухой, площадь 2,0 м2", "м2", 1.8])
    ws.append([6, "ФСБЦ-01.7.04.11-0090", "Комплект монтажный для установки дверных блоков массой до 50 кг", "компл", 1])
    ws.append(["", "", "Всего по позиции", "", ""])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _by_name(rows: list[dict], fragment: str) -> dict:
    return next(r for r in rows if fragment in r["name"])


def test_material_starting_with_blok_is_a_position():
    """«Блок дверной…» — материал, а не заголовок раздела."""
    rows = parse_xlsx_grand(_lsr_xlsx())

    material = _by_name(rows, "Блок дверной")
    assert material["is_section"] is False
    assert material["unit"] == "м2"
    assert material["quantity"] == 1.8


def test_material_reaches_claude_with_unit_and_quantity():
    """В текст для Claude материал уходит позицией, а не «=== заголовком ===».

    Разметка «===» — прямая команда промпта выбросить строку.
    """
    text = rows_to_text(parse_xlsx_grand(_lsr_xlsx()))

    assert "Блок дверной деревянный внутренний распашной глухой, площадь 2,0 м2\tм2\t1.8" in text
    assert "=== Блок" not in text


def test_real_section_header_still_recognized():
    """Настоящий заголовок раздела разделом и остаётся."""
    rows = parse_xlsx_grand(_lsr_xlsx())

    assert _by_name(rows, "Раздел 1")["is_section"] is True


def test_no_position_is_lost():
    """Все три позиции ЛСР доходят до Claude — ни одна не отфильтрована."""
    rows = parse_xlsx_grand(_lsr_xlsx())

    positions = [r["name"] for r in rows if not r["is_section"]]
    assert len(positions) == 3
    assert all("Всего по позиции" not in n for n in positions)


def test_section_word_with_unit_is_not_a_section():
    """Даже «Раздел» с единицей и объёмом — позиция: у заголовка их не бывает."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Смета"])
    ws.append(["№", "Обоснование", "Наименование работ и затрат", "Ед. изм.", "Количество"])
    ws.append([1, "ФСБЦ-1", "Раздел трубопровода фланцевый", "шт", 2])
    buf = io.BytesIO()
    wb.save(buf)

    row = _by_name(parse_xlsx_grand(buf.getvalue()), "Раздел трубопровода")
    assert row["is_section"] is False
    assert row["quantity"] == 2.0
