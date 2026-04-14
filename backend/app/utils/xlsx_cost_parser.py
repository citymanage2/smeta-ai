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


def parse_list_sheet(file_bytes: bytes) -> list[dict]:
    """
    Parse Excel file exported by generate_list():
      Sheet "Перечень" (case-insensitive, also accepts "Перечень работ" etc.)
      Columns: №, Тип, Наименование, Ед. изм., Кол-во, Примечание
    Returns list of dicts {type, name, unit, quantity, notes}.
    Raises ValueError if sheet not found or format unrecognised.
    """
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError(f"Не удалось открыть xlsx-файл: {exc}") from exc

    # Find the sheet — name must contain "перечень" (case-insensitive)
    target_ws = None
    for ws in wb.worksheets:
        if "перечень" in ws.title.lower():
            target_ws = ws
            break

    if target_ws is None:
        available = ", ".join(f'"{ws.title}"' for ws in wb.worksheets)
        raise ValueError(
            f'Лист "Перечень" не найден в файле. '
            f"Доступные листы: {available}. "
            "Убедитесь, что файл содержит лист с именем «Перечень» (или «Перечень работ»)."
        )

    items: list[dict] = []
    # Detect column positions from header row (row 1)
    header_map: dict[str, int] = {}  # canonical_key -> 0-based col index
    header_aliases = {
        "тип": "type",
        "наименование": "name",
        "ед": "unit",
        "ед.": "unit",
        "кол": "quantity",
        "кол-во": "quantity",
        "примечание": "notes",
    }

    rows_iter = target_ws.iter_rows(values_only=True)
    header_row = next(rows_iter, None)
    if header_row is None:
        raise ValueError('Лист "Перечень" пустой.')

    for col_idx, cell_val in enumerate(header_row):
        if cell_val is None:
            continue
        normalized = str(cell_val).strip().lower().rstrip(".")
        for alias, key in header_aliases.items():
            if normalized.startswith(alias):
                if key not in header_map:
                    header_map[key] = col_idx
                break

    # Fallback: assume fixed column layout (№, Тип, Наименование, Ед. изм., Кол-во, Примечание)
    if "name" not in header_map:
        header_map = {"type": 1, "name": 2, "unit": 3, "quantity": 4, "notes": 5}

    for row in rows_iter:
        if not row or all(v is None for v in row):
            continue

        name_val = row[header_map["name"]] if header_map.get("name") is not None and header_map["name"] < len(row) else None
        if name_val is None or str(name_val).strip() == "":
            continue

        item_type = ""
        if "type" in header_map and header_map["type"] < len(row):
            item_type = str(row[header_map["type"]] or "").strip()

        unit = ""
        if "unit" in header_map and header_map["unit"] < len(row):
            unit = str(row[header_map["unit"]] or "").strip()

        quantity = None
        if "quantity" in header_map and header_map["quantity"] < len(row):
            qty_raw = row[header_map["quantity"]]
            if isinstance(qty_raw, (int, float)) and not isinstance(qty_raw, bool):
                quantity = float(qty_raw)
            elif qty_raw is not None:
                try:
                    quantity = float(str(qty_raw).replace(",", "."))
                except (ValueError, TypeError):
                    quantity = None

        notes = ""
        if "notes" in header_map and header_map["notes"] < len(row):
            notes = str(row[header_map["notes"]] or "").strip()

        items.append({
            "type": item_type,
            "name": str(name_val).strip(),
            "unit": unit,
            "quantity": quantity,
            "notes": notes,
        })

    if not items:
        raise ValueError('Лист "Перечень" не содержит позиций. Проверьте содержимое файла.')

    return items
