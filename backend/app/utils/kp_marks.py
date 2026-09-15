"""Пометка строки «цена из КП» в скачиваемых xlsx оптимизации.

Строка, цена которой пришла из КП (`kp_ref`, пишет `services/kp_apply.py`),
заливается цветом «цена из КП». Цена работы, которая включает материалы, —
отдельным цветом: человеку надо проверить материал позиции, иначе он оплачен
дважды. Это только оформление — значения ячеек и итоги файла заливка не меняет.

Правило одно на оба генератора (`excel_service.generate_estimate_export`,
`xlsx_statement.generate_statement_xlsx`), чтобы файлы не расходились в цвете.
"""
from __future__ import annotations

from typing import Any, Optional

from openpyxl.styles import PatternFill

# Голубой — цена из КП; персиковый — цена работы включает материалы.
KP_FILL_COLOR = "DDEBF7"
KP_MATERIALS_FILL_COLOR = "FCE4D6"

_KP_FILL = PatternFill(start_color=KP_FILL_COLOR, end_color=KP_FILL_COLOR, fill_type="solid")
_KP_MATERIALS_FILL = PatternFill(
    start_color=KP_MATERIALS_FILL_COLOR, end_color=KP_MATERIALS_FILL_COLOR, fill_type="solid",
)

# В ведомости ключи строк — это ключи колонок документа, и у заказчика может
# быть своя колонка «kp_ref». Поэтому пометка едет служебным ключом.
STATEMENT_KP_KEY = "__kp_ref"


def kp_fill(kp_ref: Any) -> Optional[PatternFill]:
    """Заливка строки по её `kp_ref`; нет пометки (или она не объект) — None."""
    if not isinstance(kp_ref, dict) or not kp_ref:
        return None
    if kp_ref.get("includes_materials") is True:
        return _KP_MATERIALS_FILL
    return _KP_FILL
