"""Generic xlsx parser/generator for LIST and COMPLETENESS tasks.

Does NOT map columns to estimate schema — preserves xlsx structure as-is.
Row format: {"row_id": str(uuid), "cells": {"ColName": value, ...}}
"""
import io
import uuid
from datetime import datetime, date

import openpyxl

# Строку нумерации колонок («1 2 3 4 5 6») ищем только рядом с началом листа:
# ниже такая строка — уже данные, а не часть шапки.
_NUMBERING_SCAN_LIMIT = 15
# Сколько строк максимум склеиваем в одно название колонки.
_MAX_HEADER_ROWS = 4


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _non_empty_count(row) -> int:
    return sum(1 for v in row if _text(v))


def _is_numbering_row(row) -> bool:
    """Строка нумерации колонок Гранд-сметы и нашего же перечня: «1 2 3 4 5 6».

    Признаки: минимум три ячейки, все целые числа, все разные, начинается с 1 или 2,
    и значения не убегают далеко за число колонок (допускаем скрытые колонки —
    нумерация тогда идёт с пропусками).
    """
    values = [v for v in row if _text(v)]
    if len(values) < 3:
        return False

    numbers = []
    for v in values:
        if isinstance(v, bool):
            return False
        if isinstance(v, int):
            number = v
        elif isinstance(v, float) and v == int(v):
            number = int(v)
        elif _text(v).isdigit():
            number = int(_text(v))
        else:
            return False
        if not 1 <= number <= 99:
            return False
        numbers.append(number)

    if len(set(numbers)) != len(numbers):
        return False
    return min(numbers) <= 2 and max(numbers) <= len(numbers) + 3


def _detect_header(all_rows) -> tuple:
    """Вернуть (индексы строк шапки, индекс первой строки данных).

    Опорный признак — строка нумерации колонок. Она есть и в выгрузках
    Гранд-сметы, и в перечнях нашего генератора, и всегда стоит сразу под шапкой.
    Если её нет, поведение прежнее: шапка — первая строка листа.
    """
    limit = min(_NUMBERING_SCAN_LIMIT, len(all_rows))
    for idx in range(1, limit):
        if not _is_numbering_row(all_rows[idx]):
            continue
        # Шапка — строки над нумерацией, пока в них есть хотя бы две заполненные
        # ячейки. Титульный блок сметы («ЛОКАЛЬНЫЙ СМЕТНЫЙ РАСЧЁТ…») так отсекается:
        # его строки объединённые, заполненная ячейка в них одна.
        start = idx
        while start > 0 and idx - start < _MAX_HEADER_ROWS and _non_empty_count(all_rows[start - 1]) >= 2:
            start -= 1
        if start == idx:
            start = idx - 1
        return list(range(start, idx)), idx + 1

    return [0], 1


def _header_grid(ws, all_rows, header_idx: list, width: int) -> dict:
    """Матрица ячеек шапки с раскрытыми объединёнными ячейками.

    В xlsx у объединённой ячейки значение хранится только в левом верхнем углу,
    остальные приходят пустыми. Без раскрытия колонка «Стоимость, руб. / всего»
    получила бы имя «всего».
    """
    grid = {i: (list(all_rows[i]) + [None] * width)[:width] for i in header_idx}
    top, bottom = min(header_idx), max(header_idx)

    for rng in ws.merged_cells.ranges:
        r0, r1 = rng.min_row - 1, rng.max_row - 1
        c0, c1 = rng.min_col - 1, rng.max_col - 1
        if r1 < top or r0 > bottom or c0 >= width:
            continue
        if r0 >= len(all_rows) or c0 >= len(all_rows[r0]):
            continue
        value = all_rows[r0][c0]
        if value is None:
            continue
        for r in range(max(r0, top), min(r1, bottom) + 1):
            for c in range(c0, min(c1, width - 1) + 1):
                if grid[r][c] is None:
                    grid[r][c] = value

    return grid


def _build_headers(ws, all_rows, header_idx: list, width: int) -> list:
    """Склеить строки шапки в названия колонок, без пустых и без дублей."""
    grid = _header_grid(ws, all_rows, header_idx, width)

    headers = []
    for col in range(width):
        parts = []
        for row_idx in header_idx:
            part = _text(grid[row_idx][col])
            # объединённая по вертикали ячейка повторяется — не дублируем её в имени
            if part and (not parts or parts[-1] != part):
                parts.append(part)
        headers.append(" ".join(parts))

    # Одинаковые имена колонок схлопнулись бы в один ключ и потеряли данные
    seen: dict = {}
    unique = []
    for i, name in enumerate(headers):
        name = name or f"Col{i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name} ({seen[name]})"
        else:
            seen[name] = 1
        unique.append(name)

    return unique


def parse_xlsx_to_generic_rows(file_bytes: bytes) -> list[dict]:
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    ws = wb.active

    all_rows = list(ws.iter_rows(values_only=True))
    if not all_rows:
        return []

    header_idx, data_start = _detect_header(all_rows)
    width = max(len(all_rows[i]) for i in header_idx)
    headers = _build_headers(ws, all_rows, header_idx, width)

    result = []
    for raw_row in all_rows[data_start:]:
        # Skip completely empty rows
        if all(v is None for v in raw_row):
            continue

        cells: dict = {}
        for header, val in zip(headers, raw_row):
            if val is None:
                cells[header] = ""
            elif isinstance(val, (datetime, date)):
                cells[header] = val.isoformat()
            elif isinstance(val, float) and val == int(val):
                cells[header] = int(val)
            else:
                cells[header] = val

        result.append({"row_id": str(uuid.uuid4()), "cells": cells})

    return result


def rows_to_xlsx(rows: list[dict]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active

    if not rows:
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    # Collect column order from all rows, preserving first-seen order
    all_keys: list[str] = list(dict.fromkeys(k for row in rows for k in row.get("cells", {}).keys()))

    ws.append(all_keys)
    for row in rows:
        cells = row.get("cells", {})
        ws.append([cells.get(k, "") for k in all_keys])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
