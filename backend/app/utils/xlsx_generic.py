"""Generic xlsx parser/generator for LIST and COMPLETENESS tasks.

Does NOT map columns to estimate schema — preserves xlsx structure as-is.
Row format: {"row_id": str(uuid), "cells": {"ColName": value, ...}}
"""
import io
import uuid
from datetime import datetime, date

import openpyxl


def parse_xlsx_to_generic_rows(file_bytes: bytes) -> list[dict]:
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    ws = wb.active

    all_rows = list(ws.iter_rows(values_only=True))
    if not all_rows:
        return []

    # First row = headers; empty header cells get placeholder names
    raw_headers = all_rows[0]
    headers = [
        str(h).strip() if h is not None else f"Col{i + 1}"
        for i, h in enumerate(raw_headers)
    ]

    result = []
    for raw_row in all_rows[1:]:
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
