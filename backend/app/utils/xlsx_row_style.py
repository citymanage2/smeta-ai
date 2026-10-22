"""Строка материала в скачиваемых xlsx: синий курсив, текст прижат вправо.

Материал под работой читается как её часть: менеджер видит, к какой работе он
относится, не глядя в колонку «Тип». Правило родилось в перечне (25.05.2026,
`excel_service._write_perechen_sheet`) и одно на все файлы со строками —
перечень, смету, версию оптимизации, сравнение версий и разделы сводной.
Раньше оно жило только в перечне, и в остальных файлах материал выглядел так
же, как работа.

Это только оформление: значения ячеек, форматы чисел и итоги не меняются.
Шрифт файла (гарнитура, кегль, жирность) сохраняется — меняются курсив и цвет.
"""
from __future__ import annotations

from typing import Any

from openpyxl.styles import Alignment, Font

from app.utils.estimate_rows import canonical_type

MATERIAL_FONT_COLOR = "4284F3"


def is_material(raw_type: Any) -> bool:
    return canonical_type(raw_type) == "material"


def is_work(raw_type: Any) -> bool:
    return canonical_type(raw_type) == "work"


def style_material_cell(cell, *, right: bool = False) -> None:
    """Синий курсив поверх шрифта ячейки; `right` — прижать текст вправо.

    Вызывать после того, как генератор поставил ячейке свой шрифт и
    выравнивание: от них берутся гарнитура, кегль, перенос и вертикаль.
    """
    font = cell.font
    cell.font = Font(
        name=font.name, size=font.size, bold=font.bold,
        italic=True, color=MATERIAL_FONT_COLOR,
    )
    if right:
        alignment = cell.alignment
        cell.alignment = Alignment(
            horizontal="right",
            vertical=alignment.vertical,
            wrap_text=alignment.wrap_text,
        )
