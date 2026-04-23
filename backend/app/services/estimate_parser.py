"""Parse an estimate Excel file into a list of EstimateRow dicts.

Each returned dict matches EstimateRowSchema.
"""
import io
import uuid
from typing import Optional

import openpyxl


# Keywords used to detect column roles (case-insensitive, stripped)
_NUM_KW = ("№", "num", "n", "п/п", "пп")
_TYPE_KW = ("тип", "вид", "type")
_NAME_KW = ("наименование", "наименов", "name", "описание")
_UNIT_KW = ("ед", "unit", "ед.изм", "единица")
_QTY_KW = ("кол", "qty", "количество", "объем", "объём")
_PRICE_WORK_KW = ("цена работ", "труд", "labor", "работа", "стоим.работ", "price_work", "цр")
_PRICE_MAT_KW = ("цена матер", "матер", "material", "price_material", "цм", "стоим.матер")
_SKIP_KW = ("стоимость", "сумма", "итого", "total", "cost", "всего")


def _header_matches(cell_val: str, keywords: tuple) -> bool:
    v = cell_val.lower().strip()
    return any(v.startswith(k) or k in v for k in keywords)


def _to_float(val) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        f = float(val)
        return f if f != 0.0 else None
    s = str(val).strip().replace(" ", "").replace("\xa0", "").replace(",", ".")
    try:
        f = float(s)
        return f if f != 0.0 else None
    except (ValueError, TypeError):
        return None


def _detect_columns(header_row: list) -> dict:
    """Return {role: col_index} mapping from a header row (0-based)."""
    cols: dict = {}
    for idx, cell in enumerate(header_row):
        if cell is None:
            continue
        v = str(cell)
        if "num" not in cols and _header_matches(v, _NUM_KW):
            cols["num"] = idx
        elif "type" not in cols and _header_matches(v, _TYPE_KW):
            cols["type"] = idx
        elif "name" not in cols and _header_matches(v, _NAME_KW):
            cols["name"] = idx
        elif "unit" not in cols and _header_matches(v, _UNIT_KW):
            cols["unit"] = idx
        elif "qty" not in cols and _header_matches(v, _QTY_KW):
            cols["qty"] = idx
        elif "price_work" not in cols and _header_matches(v, _PRICE_WORK_KW):
            cols["price_work"] = idx
        elif "price_material" not in cols and _header_matches(v, _PRICE_MAT_KW):
            cols["price_material"] = idx
    return cols


def _infer_type(price_work: Optional[float], price_material: Optional[float]) -> str:
    pw = price_work or 0.0
    pm = price_material or 0.0
    if pw > 0 and pm == 0:
        return "work"
    if pm > 0 and pw == 0:
        return "material"
    if pw > 0 and pm > 0:
        return "work"
    return "section"


def parse_estimate_excel(file_bytes: bytes) -> list[dict]:
    """Parse xlsx bytes into a list of EstimateRow dicts.

    Uses openpyxl with data_only=True so formula cells return computed values.
    Returns an empty list if the file cannot be parsed or no recognizable header found.
    """
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    except Exception:
        return []

    ws = wb.active

    rows_raw = list(ws.iter_rows(values_only=True))
    if not rows_raw:
        return []

    # Find header row: first row that contains a name-like keyword
    header_idx: Optional[int] = None
    cols: dict = {}
    for i, row in enumerate(rows_raw):
        row_strs = [str(c) if c is not None else "" for c in row]
        combined = " ".join(row_strs).lower()
        if any(k in combined for k in ("наименование", "наименов", "name")):
            cols = _detect_columns(row_strs)
            if "name" in cols:
                header_idx = i
                break

    if header_idx is None or "name" not in cols:
        return []

    result = []
    num_counter = 0

    for row in rows_raw[header_idx + 1:]:
        name_val = row[cols["name"]] if "name" in cols and cols["name"] < len(row) else None
        if name_val is None or str(name_val).strip() == "":
            continue

        name = str(name_val).strip()

        # Skip obvious total/footer rows
        low = name.lower()
        if any(k in low for k in ("итого", "всего", "total", "grand total", "в том числе")):
            continue

        num_val = row[cols["num"]] if "num" in cols and cols["num"] < len(row) else None
        num = None
        if num_val is not None:
            try:
                num = int(float(str(num_val)))
            except (ValueError, TypeError):
                pass
        if num is None:
            num_counter += 1
            num = num_counter

        unit_val = row[cols["unit"]] if "unit" in cols and cols["unit"] < len(row) else None
        unit = str(unit_val).strip() if unit_val is not None else ""

        qty_val = row[cols["qty"]] if "qty" in cols and cols["qty"] < len(row) else None
        qty = _to_float(qty_val)

        pw_val = row[cols["price_work"]] if "price_work" in cols and cols["price_work"] < len(row) else None
        pm_val = row[cols["price_material"]] if "price_material" in cols and cols["price_material"] < len(row) else None
        price_work = _to_float(pw_val)
        price_material = _to_float(pm_val)

        if "type" in cols and cols["type"] < len(row):
            raw_type = str(row[cols["type"]] or "").lower().strip()
            if "работ" in raw_type or raw_type in ("work", "w", "р"):
                row_type = "work"
            elif "матер" in raw_type or raw_type in ("material", "m", "м"):
                row_type = "material"
            else:
                row_type = _infer_type(price_work, price_material)
        else:
            row_type = _infer_type(price_work, price_material)

        cost: Optional[float] = None
        if qty is not None:
            pw = price_work or 0.0
            pm = price_material or 0.0
            cost = round(qty * (pw + pm), 2) if (pw + pm) > 0 else None

        row_id = str(uuid.uuid4())
        result.append({
            "id": row_id,
            "lineage_id": row_id,
            "num": num,
            "type": row_type,
            "name": name,
            "unit": unit,
            "qty": qty,
            "price_work": price_work,
            "price_material": price_material,
            "cost": cost,
            "selected": False,
            "abc_group": None,
            "optimization_note": None,
        })

    return result
