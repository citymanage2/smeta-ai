import io
from decimal import Decimal
from typing import Optional

import openpyxl


def extract_total_cost(file_bytes: bytes) -> Optional[Decimal]:
    """
    Ищет строку где первая ячейка содержит 'итого' или 'всего'
    (регистронезависимо, после strip).
    Возвращает последнее числовое значение в этой строке.
    Если найдено несколько таких строк — берёт последнюю.
    Если ничего не найдено — возвращает None.
    """
    try:
        wb = openpyxl.load_workbook(
            io.BytesIO(file_bytes), read_only=True, data_only=True
        )
    except Exception:
        return None

    last_cost: Optional[Decimal] = None

    for ws in wb.worksheets:
        for row in ws.iter_rows():
            if not row:
                continue
            first_val = row[0].value
            if first_val is None:
                continue
            normalized = str(first_val).strip().lower()
            if "итого" not in normalized and "всего" not in normalized:
                continue
            # Find last numeric value in this row
            for cell in reversed(row):
                val = cell.value
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    last_cost = Decimal(str(val))
                    break

    return last_cost
