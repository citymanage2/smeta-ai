"""Строки generic-документа → позиции перечня.

Перечень и результат проверки полноты живут в редакторе как плоские строки
«как в файле»: `{row_id, sheet, cells: {"Наименование": …}}`. А смету со стадии
«После проверки полноты» строит `task.progress_data['items']` — позиции вида
`{type, name, unit, quantity, notes, sheet}`.

Пока перевода между ними не было, правки человека в редакторе оставались в
документе и в скачиваемом файле, но в смету уезжал перечень до правок: он
читается из `progress_data`, а тот писался только обработчиком задачи.

Разбор колонок повторяет `xlsx_cost_parser._parse_list_worksheet` — это тот же
файл, только уже разобранный на строки, и контракт позиции обязан совпасть.
"""
from __future__ import annotations

from typing import Any, Optional

_HEADER_ALIASES = {
    "тип": "type",
    "наименование": "name",
    "ед": "unit",
    "кол": "quantity",
    "примечание": "notes",
}


def _column_map(cells: dict) -> dict[str, str]:
    """Название колонки в документе → поле позиции."""
    mapping: dict[str, str] = {}
    for column in cells:
        normalized = str(column).strip().lower().rstrip(".")
        for alias, key in _HEADER_ALIASES.items():
            if normalized.startswith(alias) and key not in mapping.values():
                mapping[column] = key
                break
    return mapping


def _number(value: Any) -> Optional[float]:
    """Объём числом. Текст вроде «по проекту» числом не становится и теряется —
    ровно так же, как при разборе того же файла из xlsx."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "").replace("\xa0", "").replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def generic_rows_to_items(rows: list) -> list[dict]:
    """Позиции перечня из строк документа. Строки без наименования пропускаются."""
    items: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        cells = row.get("cells")
        if not isinstance(cells, dict):
            continue

        mapping = _column_map(cells)
        values: dict[str, Any] = {}
        for column, key in mapping.items():
            values[key] = cells.get(column)

        name = str(values.get("name") or "").strip()
        if not name:
            continue

        item = {
            "type": str(values.get("type") or "").strip(),
            "name": name,
            "unit": str(values.get("unit") or "").strip(),
            "quantity": _number(values.get("quantity")),
            "notes": str(values.get("notes") or "").strip(),
        }
        sheet = row.get("sheet")
        if sheet:
            item["sheet"] = str(sheet)
        items.append(item)
    return items
