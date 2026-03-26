# Optimization Iteration 3 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add estimate optimization module: parse xlsx estimate, find cheaper analogues via price-list + Claude web-search, generate optimized xlsx with comparison sheet.

**Architecture:** Two new endpoints (`/optimize/analyze` sync + `/optimize/run` background) added to existing tasks router. New utility module `xlsx_optimizer.py` handles parsing/generation. 4-step wizard modal on ProjectDetail page triggers the flow.

**Tech Stack:** FastAPI + openpyxl + existing price_service.py (Claude web-search) / React + TypeScript

**Spec:** `docs/superpowers/specs/2026-03-26-optimization-iteration-3-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `backend/app/constants.py` | Modify | Add `OPTIMIZE_SMETA` task type + `processing_optimization` status |
| `backend/app/utils/xlsx_optimizer.py` | Create | Parse estimate xlsx, select top-70% items, generate optimized xlsx |
| `backend/tests/test_xlsx_optimizer.py` | Create | 8 unit tests for xlsx_optimizer functions |
| `backend/app/routers/tasks.py` | Modify | Add `POST /tasks/{id}/optimize/analyze` and `/optimize/run` |
| `backend/tests/test_optimize_endpoint.py` | Create | 4 integration tests for optimization endpoints |
| `backend/app/services/task_processor.py` | Modify | Add `OPTIMIZE_SMETA` task type handler |
| `frontend/src/types/index.ts` | Modify | Add `OPTIMIZE_SMETA` TaskType, `processing_optimization` EstimationStatus |
| `frontend/src/api/tasks.ts` | Modify | Add `analyzeOptimize()`, `runOptimize()` + response types |
| `frontend/src/components/TaskTypeSelector.tsx` | Modify | Add `OPTIMIZE_SMETA` option |
| `frontend/src/components/OptimizeModal.tsx` | Create | 4-step wizard: categories → table → progress → results |
| `frontend/src/pages/ProjectDetail.tsx` | Modify | "Оптимизировать" button + OptimizeModal mounting |

---

## Task 1: Update constants

**Files:**
- Modify: `backend/app/constants.py`

Current state of the file (key sections):
```python
ESTIMATE_TASK_TYPES = {"SMETA_FROM_LIST", "SMETA_FROM_PROJECT", "SMETA_FROM_EDC_PROJECT", "SMETA_FROM_GRAND_PROJECT", "SCAN_TO_EXCEL"}
ESTIMATION_STATUS_LABELS = {"unestimated": "Не рассчитано", "estimated": "Рассчитано", "optimized": "Оптимизировано", "not_applicable": "—"}
TASK_TYPE_LABELS = { ... }  # existing mapping
```

- [ ] **Step 1: Read current constants.py**

```bash
cat backend/app/constants.py
```

- [ ] **Step 2: Add OPTIMIZE_SMETA to TASK_TYPE_LABELS, ESTIMATE_TASK_TYPES; add processing_optimization to ESTIMATION_STATUS_LABELS**

In `backend/app/constants.py`, add to `TASK_TYPE_LABELS`:
```python
"OPTIMIZE_SMETA": "Оптимизация сметы",
```

Add to `ESTIMATE_TASK_TYPES`:
```python
"OPTIMIZE_SMETA",
```

Add to `ESTIMATION_STATUS_LABELS`:
```python
"processing_optimization": "Оптимизируется",
```

- [ ] **Step 3: Run existing tests to make sure nothing broke**

```bash
cd backend && python -m pytest tests/ -q --tb=short
```
Expected: all tests pass (148+)

- [ ] **Step 4: Commit**

```bash
git add backend/app/constants.py
git commit -m "feat: add OPTIMIZE_SMETA task type and processing_optimization status"
```

---

## Task 2: Create xlsx_optimizer.py utility + tests

**Files:**
- Create: `backend/app/utils/xlsx_optimizer.py`
- Create: `backend/tests/test_xlsx_optimizer.py`

The smeta xlsx format (from `excel_service.py`):
- Col 1: № | Col 2: Тип | Col 3: Наименование | Col 4: Ед. изм.
- Col 5: Кол-во | Col 6: Цена работы (за ед.) | Col 7: Цена материала (за ед.)
- Col 8: Стоимость работ | Col 9: Стоимость материалов
- Col 10: Итого без НДС | Col 11: НДС (20%) | Col 12: Итого с НДС
- Row 1 = header, Row 2+ = data, last row = ИТОГО total

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_xlsx_optimizer.py`:

```python
"""Tests for xlsx_optimizer utility."""
import io
import pytest
import openpyxl
from openpyxl.styles import PatternFill

from app.utils.xlsx_optimizer import (
    parse_estimate_xlsx,
    get_top_items,
    generate_optimized_xlsx,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_smeta_xlsx(items: list[dict]) -> bytes:
    """Build a minimal smeta xlsx in the format excel_service.generate_smeta() produces."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Смета"
    headers = [
        "№", "Тип", "Наименование", "Ед. изм.", "Кол-во",
        "Цена работы (за ед.)", "Цена материала (за ед.)",
        "Стоимость работ", "Стоимость материалов",
        "Итого без НДС", "НДС (20%)", "Итого с НДС",
        "Наименование в прайсе", "Источники", "Примечание",
    ]
    for col, h in enumerate(headers, start=1):
        ws.cell(row=1, column=col, value=h)
    VAT = 0.20
    for i, item in enumerate(items, start=1):
        row = i + 1
        qty = item.get("quantity", 1)
        wp = item.get("work_price", 0)
        mp = item.get("material_price", 0)
        subtotal = qty * (wp + mp)
        vat = subtotal * VAT
        total = subtotal + vat
        ws.cell(row=row, column=1, value=i)
        ws.cell(row=row, column=2, value=item.get("type", "Материал"))
        ws.cell(row=row, column=3, value=item["name"])
        ws.cell(row=row, column=4, value=item.get("unit", "шт"))
        ws.cell(row=row, column=5, value=qty)
        ws.cell(row=row, column=6, value=wp or None)
        ws.cell(row=row, column=7, value=mp or None)
        ws.cell(row=row, column=8, value=qty * wp or None)
        ws.cell(row=row, column=9, value=qty * mp or None)
        ws.cell(row=row, column=10, value=subtotal or None)
        ws.cell(row=row, column=11, value=vat or None)
        ws.cell(row=row, column=12, value=total or None)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_smeta_items():
    """Return 5 test items with varying total costs."""
    return [
        {"name": "Кирпич М150", "type": "Материал", "unit": "шт", "quantity": 1000, "material_price": 10.0},   # total=12000
        {"name": "Монтаж трубы", "type": "Работа", "unit": "м", "quantity": 50, "work_price": 500.0},           # total=30000
        {"name": "Цемент М400", "type": "Материал", "unit": "кг", "quantity": 200, "material_price": 20.0},    # total=4800
        {"name": "Устройство стяжки", "type": "Работа", "unit": "м2", "quantity": 100, "work_price": 300.0},   # total=36000
        {"name": "Гвозди 100мм", "type": "Материал", "unit": "кг", "quantity": 10, "material_price": 50.0},   # total=600
    ]
    # Sorted by total desc: Устройство стяжки(36k), Монтаж трубы(30k), Кирпич М150(12k), Цемент М400(4.8k), Гвозди(600)
    # Grand total = 83400
    # 70% threshold = 58380 → need Устройство(36k) + Монтаж(30k) = 66k > 58380 → first 2 items


# ---------------------------------------------------------------------------
# parse_estimate_xlsx tests
# ---------------------------------------------------------------------------

def test_parse_estimate_xlsx_returns_items():
    """Parsing a well-formed smeta xlsx returns list of items with correct fields."""
    items = _make_smeta_items()[:3]
    file_bytes = _make_smeta_xlsx(items)
    result = parse_estimate_xlsx(file_bytes)
    assert len(result) == 3
    first = result[0]
    assert first["name"] == "Кирпич М150"
    assert first["type"] == "material"
    assert first["unit"] == "шт"
    assert first["quantity"] == 1000
    assert isinstance(first["row_index"], int)
    assert isinstance(first["price_excl_vat"], float)
    assert isinstance(first["price_incl_vat"], float)
    assert isinstance(first["total"], float)
    assert first["price_incl_vat"] > first["price_excl_vat"]


def test_parse_estimate_xlsx_skips_empty_rows():
    """Rows with no name value are skipped."""
    items = _make_smeta_items()[:2]
    wb = openpyxl.Workbook()
    ws = wb.active
    headers = ["№", "Тип", "Наименование", "Ед. изм.", "Кол-во", "Цена работы (за ед.)", "Цена материала (за ед.)",
               "Стоимость работ", "Стоимость материалов", "Итого без НДС", "НДС (20%)", "Итого с НДС",
               "Наименование в прайсе", "Источники", "Примечание"]
    for col, h in enumerate(headers, start=1):
        ws.cell(row=1, column=col, value=h)
    # Row 2: valid item
    ws.cell(row=2, column=2, value="Материал")
    ws.cell(row=2, column=3, value="Кирпич М150")
    ws.cell(row=2, column=5, value=100)
    ws.cell(row=2, column=7, value=10.0)
    ws.cell(row=2, column=12, value=1200.0)
    # Row 3: empty name (ИТОГО row)
    ws.cell(row=3, column=1, value="ИТОГО")
    buf = io.BytesIO()
    wb.save(buf)
    result = parse_estimate_xlsx(buf.getvalue())
    assert len(result) == 1
    assert result[0]["name"] == "Кирпич М150"


# ---------------------------------------------------------------------------
# get_top_items tests
# ---------------------------------------------------------------------------

def test_get_top_items_covers_threshold():
    """Selected items' cumulative total covers at least 70% of grand total."""
    items = _make_smeta_items()
    file_bytes = _make_smeta_xlsx(items)
    parsed = parse_estimate_xlsx(file_bytes)
    selected = get_top_items(parsed, categories=["work", "material"], threshold=0.7)
    grand_total = sum(it["total"] for it in parsed)
    selected_total = sum(it["total"] for it in selected)
    assert selected_total >= 0.7 * grand_total


def test_get_top_items_filters_categories():
    """Only items matching the requested categories are returned."""
    items = _make_smeta_items()
    file_bytes = _make_smeta_xlsx(items)
    parsed = parse_estimate_xlsx(file_bytes)
    # Ask only for materials
    selected = get_top_items(parsed, categories=["material"], threshold=0.99)
    assert all(it["type"] == "material" for it in selected)


# ---------------------------------------------------------------------------
# generate_optimized_xlsx tests
# ---------------------------------------------------------------------------

def _make_optimization_results(items_parsed: list[dict]) -> list[dict]:
    """Build mock optimization_results: first item found, rest not found."""
    results = []
    for i, it in enumerate(items_parsed):
        if i == 0:
            results.append({
                "row_index": it["row_index"],
                "name": it["name"],
                "original_price": it["price_incl_vat"],
                "new_price": it["price_incl_vat"] * 0.8,
                "source": "https://example.com/price",
                "savings_abs": it["price_incl_vat"] * 0.2,
                "savings_pct": 20.0,
                "has_vat": True,
            })
        else:
            results.append({
                "row_index": it["row_index"],
                "name": it["name"],
                "original_price": it["price_incl_vat"],
                "new_price": None,
                "source": "Не найдено",
                "savings_abs": None,
                "savings_pct": None,
                "has_vat": True,
            })
    return results


def test_generate_optimized_xlsx_adds_columns():
    """Optimized xlsx has 4 extra columns after original columns."""
    items = _make_smeta_items()[:3]
    original_bytes = _make_smeta_xlsx(items)
    parsed = parse_estimate_xlsx(original_bytes)
    opt_results = _make_optimization_results(parsed)
    result_bytes = generate_optimized_xlsx(original_bytes, opt_results)
    wb = openpyxl.load_workbook(io.BytesIO(result_bytes))
    ws = wb.active
    # Original has 15 columns; optimized adds 4 more
    header_row = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
    assert "Цена сниженная" in header_row
    assert "Стоимость сниженная" in header_row
    assert "Источник" in header_row
    assert "Примечание" in header_row


def test_generate_optimized_xlsx_has_comparison_sheet():
    """Result workbook contains a second sheet named 'Сравнение'."""
    items = _make_smeta_items()[:2]
    original_bytes = _make_smeta_xlsx(items)
    parsed = parse_estimate_xlsx(original_bytes)
    opt_results = _make_optimization_results(parsed)
    result_bytes = generate_optimized_xlsx(original_bytes, opt_results)
    wb = openpyxl.load_workbook(io.BytesIO(result_bytes))
    assert "Сравнение" in wb.sheetnames


def test_generate_optimized_xlsx_green_fill_for_found():
    """Rows with a found analogue get green fill (#E2EFDA) in the 'Цена сниженная' column."""
    items = _make_smeta_items()[:2]
    original_bytes = _make_smeta_xlsx(items)
    parsed = parse_estimate_xlsx(original_bytes)
    # First item found
    opt_results = _make_optimization_results(parsed)
    result_bytes = generate_optimized_xlsx(original_bytes, opt_results)
    wb = openpyxl.load_workbook(io.BytesIO(result_bytes))
    ws = wb.active
    # Find the "Цена сниженная" column index
    price_col = None
    for c in range(1, ws.max_column + 1):
        if ws.cell(row=1, column=c).value == "Цена сниженная":
            price_col = c
            break
    assert price_col is not None
    # Data row for first item = row 2; first opt_result has new_price (found)
    found_row = parsed[0]["row_index"]
    cell = ws.cell(row=found_row, column=price_col)
    assert cell.fill.fgColor.rgb.upper().endswith("E2EFDA")


def test_generate_optimized_xlsx_yellow_fill_for_not_found():
    """Rows with no analogue get yellow fill (#FFEB9C) in the 'Цена сниженная' column."""
    items = _make_smeta_items()[:2]
    original_bytes = _make_smeta_xlsx(items)
    parsed = parse_estimate_xlsx(original_bytes)
    opt_results = _make_optimization_results(parsed)  # item[1] is not found
    result_bytes = generate_optimized_xlsx(original_bytes, opt_results)
    wb = openpyxl.load_workbook(io.BytesIO(result_bytes))
    ws = wb.active
    price_col = None
    for c in range(1, ws.max_column + 1):
        if ws.cell(row=1, column=c).value == "Цена сниженная":
            price_col = c
            break
    # Second item = not found
    not_found_row = parsed[1]["row_index"]
    cell = ws.cell(row=not_found_row, column=price_col)
    assert cell.fill.fgColor.rgb.upper().endswith("FFEB9C")
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && python -m pytest tests/test_xlsx_optimizer.py -v 2>&1 | head -30
```
Expected: `ModuleNotFoundError: No module named 'app.utils.xlsx_optimizer'`

- [ ] **Step 3: Create xlsx_optimizer.py**

Create `backend/app/utils/xlsx_optimizer.py`:

```python
"""Utilities for parsing and optimizing estimate xlsx files."""
import io
from typing import Optional
import openpyxl
from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter

# Heuristic keywords for "work" type detection
_WORK_KEYWORDS = ("монтаж", "устройство", "разборка", "прокладка", "установка",
                  "укладка", "демонтаж", "сборка", "покраска", "штукатурка",
                  "кладка", "бурение", "сварка", "резка")

# "Extra" row keywords — накладные расходы, итого, НДС
_EXTRA_KEYWORDS = ("накладные", "прибыль", "ндс", "итого", "сметная прибыль", "всего")

_GREEN_FILL = PatternFill("solid", fgColor="E2EFDA")
_YELLOW_FILL = PatternFill("solid", fgColor="FFEB9C")

VAT_RATE = 0.20


def _detect_type(type_cell_value: Optional[str], name: str) -> str:
    """Determine item type from explicit column or heuristic."""
    if type_cell_value:
        v = type_cell_value.strip().lower()
        if v in ("работа", "работы", "work"):
            return "work"
        if v in ("материал", "материалы", "material"):
            return "material"
        if any(k in v for k in ("накладн", "ндс", "прибыль", "итого")):
            return "extra"

    name_lower = name.lower()
    if any(k in name_lower for k in _EXTRA_KEYWORDS):
        return "extra"
    if any(k in name_lower for k in _WORK_KEYWORDS):
        return "work"
    return "material"


def _find_header_row(ws) -> Optional[int]:
    """Find the header row index (1-based) in the first 10 rows."""
    for row_idx in range(1, min(11, ws.max_row + 1)):
        for col in range(1, min(20, ws.max_column + 1)):
            val = ws.cell(row=row_idx, column=col).value
            if val and isinstance(val, str):
                lower = val.lower()
                if any(k in lower for k in ("наименование", "назван")):
                    return row_idx
    return None


def _map_columns(ws, header_row: int) -> dict:
    """Return mapping of logical field -> column index (1-based)."""
    mapping: dict[str, int] = {}
    for col in range(1, ws.max_column + 1):
        val = ws.cell(row=header_row, column=col).value
        if not val or not isinstance(val, str):
            continue
        lower = val.strip().lower()
        if "наименование" in lower or "назван" in lower:
            mapping.setdefault("name", col)
        elif "тип" in lower:
            mapping.setdefault("type", col)
        elif "ед" in lower and ("изм" in lower or "." in lower):
            mapping.setdefault("unit", col)
        elif "кол" in lower:
            mapping.setdefault("quantity", col)
        elif "итого с" in lower or ("итого" in lower and "ндс" in lower and "без" not in lower):
            mapping.setdefault("total_incl_vat", col)
        elif "итого без" in lower or ("итого" in lower and "без" in lower):
            mapping.setdefault("total_excl_vat", col)
        elif "ндс" in lower and "%" in lower:
            mapping.setdefault("vat_col", col)
        elif ("цена" in lower or "стоим" in lower) and ("работ" in lower or "труд" in lower):
            mapping.setdefault("work_price", col)
        elif ("цена" in lower or "стоим" in lower) and "матер" in lower:
            mapping.setdefault("material_price", col)
        elif "цена" in lower and "ед" in lower:
            mapping.setdefault("unit_price", col)
    return mapping


def parse_estimate_xlsx(file_bytes: bytes) -> list[dict]:
    """
    Parse estimate xlsx. Finds header row by 'наименование' keyword in first 10 rows.
    Returns list of items: {row_index, name, type, quantity, unit,
                             price_excl_vat, price_incl_vat, total}
    Skips rows without a name value and rows matching 'extra' keywords (totals/НДС rows).
    """
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    ws = wb.active

    header_row = _find_header_row(ws)
    if header_row is None:
        raise ValueError("Не удалось найти строку заголовков в xlsx (поиск по 'наименование')")

    cols = _map_columns(ws, header_row)
    if "name" not in cols:
        raise ValueError("Колонка 'Наименование' не найдена в xlsx")

    items = []
    for row_idx in range(header_row + 1, ws.max_row + 1):
        name_cell = ws.cell(row=row_idx, column=cols["name"])
        name = name_cell.value
        if not name or not str(name).strip():
            continue
        name = str(name).strip()

        # Skip extra / total rows
        type_raw = ""
        if "type" in cols:
            type_val = ws.cell(row=row_idx, column=cols["type"]).value
            type_raw = str(type_val).strip() if type_val else ""

        item_type = _detect_type(type_raw, name)
        if item_type == "extra":
            continue

        quantity = 0.0
        if "quantity" in cols:
            q = ws.cell(row=row_idx, column=cols["quantity"]).value
            quantity = float(q) if q is not None else 0.0

        unit = ""
        if "unit" in cols:
            u = ws.cell(row=row_idx, column=cols["unit"]).value
            unit = str(u).strip() if u else ""

        # Calculate price_excl_vat (per unit)
        price_excl_vat = 0.0
        if "work_price" in cols:
            wp = ws.cell(row=row_idx, column=cols["work_price"]).value
            price_excl_vat += float(wp) if wp else 0.0
        if "material_price" in cols:
            mp = ws.cell(row=row_idx, column=cols["material_price"]).value
            price_excl_vat += float(mp) if mp else 0.0

        # Fallback: if no work/material price cols, try unit_price col
        if price_excl_vat == 0.0 and "unit_price" in cols:
            up = ws.cell(row=row_idx, column=cols["unit_price"]).value
            price_excl_vat = float(up) if up else 0.0

        # Fallback: derive from total_excl_vat / quantity
        if price_excl_vat == 0.0 and "total_excl_vat" in cols and quantity:
            tv = ws.cell(row=row_idx, column=cols["total_excl_vat"]).value
            if tv:
                price_excl_vat = float(tv) / quantity

        price_incl_vat = price_excl_vat * (1 + VAT_RATE)

        # Total (incl VAT)
        total = 0.0
        if "total_incl_vat" in cols:
            t = ws.cell(row=row_idx, column=cols["total_incl_vat"]).value
            total = float(t) if t else 0.0
        if total == 0.0:
            total = quantity * price_incl_vat

        items.append({
            "row_index": row_idx,
            "name": name,
            "type": item_type,
            "quantity": quantity,
            "unit": unit,
            "price_excl_vat": round(price_excl_vat, 4),
            "price_incl_vat": round(price_incl_vat, 4),
            "total": round(total, 2),
        })

    return items


def get_top_items(items: list[dict], categories: list[str], threshold: float = 0.7) -> list[dict]:
    """
    Filter by categories, sort by total descending, return items until
    cumulative sum crosses threshold * grand_total.
    All returned items have selected=True added.
    """
    filtered = [it for it in items if it["type"] in categories]
    if not filtered:
        return []

    grand_total = sum(it["total"] for it in filtered)
    if grand_total == 0:
        return []

    sorted_items = sorted(filtered, key=lambda x: x["total"], reverse=True)
    target = threshold * grand_total
    cumulative = 0.0
    result = []
    for it in sorted_items:
        cumulative += it["total"]
        result.append({**it, "selected": True})
        if cumulative >= target:
            break

    return result


def generate_optimized_xlsx(original_bytes: bytes, optimization_results: list[dict]) -> bytes:
    """
    Open original xlsx, add 4 columns to first sheet:
      'Цена сниженная', 'Стоимость сниженная', 'Источник', 'Примечание'
    Apply green fill (#E2EFDA) for found analogues, yellow (#FFEB9C) for 'Не найдено'.
    Add sheet 'Сравнение' with before/after comparison table.
    Returns modified xlsx as bytes.
    """
    wb = openpyxl.load_workbook(io.BytesIO(original_bytes))
    ws = wb.active

    # Find how many columns exist
    last_col = ws.max_column
    new_price_col = last_col + 1
    new_total_col = last_col + 2
    source_col = last_col + 3
    note_col = last_col + 4

    ws.cell(row=1, column=new_price_col, value="Цена сниженная")
    ws.cell(row=1, column=new_total_col, value="Стоимость сниженная")
    ws.cell(row=1, column=source_col, value="Источник")
    ws.cell(row=1, column=note_col, value="Примечание")

    # Build row_index → result map
    result_map = {r["row_index"]: r for r in optimization_results}

    for opt in optimization_results:
        row_idx = opt["row_index"]
        new_price = opt.get("new_price")
        source = opt.get("source", "Не найдено")

        fill = _GREEN_FILL if new_price is not None else _YELLOW_FILL

        # Determine quantity from the row
        # Find quantity column: col 5 in standard smeta
        qty = None
        for c in range(1, ws.max_column + 1):
            h = ws.cell(row=1, column=c).value
            if h and isinstance(h, str) and "кол" in h.lower():
                qty = ws.cell(row=row_idx, column=c).value
                break

        new_total = None
        if new_price is not None and qty:
            try:
                new_total = round(float(new_price) * float(qty), 2)
            except (TypeError, ValueError):
                pass

        price_cell = ws.cell(row=row_idx, column=new_price_col)
        price_cell.value = round(new_price, 4) if new_price is not None else "Не найдено"
        price_cell.fill = fill

        total_cell = ws.cell(row=row_idx, column=new_total_col)
        total_cell.value = round(new_total, 2) if new_total is not None else None
        total_cell.fill = fill

        source_cell = ws.cell(row=row_idx, column=source_col)
        source_cell.value = source
        source_cell.fill = fill

        note_cell = ws.cell(row=row_idx, column=note_col)
        savings_pct = opt.get("savings_pct")
        if savings_pct is not None:
            note_cell.value = f"Экономия {savings_pct:.1f}%"
        note_cell.fill = fill

    # Add comparison sheet
    ws_cmp = wb.create_sheet("Сравнение")
    cmp_headers = ["Наименование", "Тип", "Кол-во", "Ед.", "Цена было", "Цена стало",
                   "Экономия на ед.", "Экономия %", "Источник"]
    for col, h in enumerate(cmp_headers, start=1):
        ws_cmp.cell(row=1, column=col, value=h)

    total_savings = 0.0
    total_original = 0.0

    for i, opt in enumerate(optimization_results, start=2):
        ws_cmp.cell(row=i, column=1, value=opt.get("name", ""))
        ws_cmp.cell(row=i, column=3, value=None)  # qty not directly available
        ws_cmp.cell(row=i, column=5, value=round(opt.get("original_price", 0), 4))
        new_price = opt.get("new_price")
        ws_cmp.cell(row=i, column=6, value=round(new_price, 4) if new_price is not None else "Не найдено")
        savings_abs = opt.get("savings_abs")
        ws_cmp.cell(row=i, column=7, value=round(savings_abs, 4) if savings_abs is not None else None)
        savings_pct = opt.get("savings_pct")
        ws_cmp.cell(row=i, column=8, value=round(savings_pct, 2) if savings_pct is not None else None)
        ws_cmp.cell(row=i, column=9, value=opt.get("source", ""))
        if savings_abs is not None:
            total_savings += savings_abs
        total_original += opt.get("original_price", 0)

    # Summary row
    summary_row = len(optimization_results) + 2
    ws_cmp.cell(row=summary_row, column=1, value="ИТОГО экономия")
    ws_cmp.cell(row=summary_row, column=7, value=round(total_savings, 2))
    if total_original > 0:
        ws_cmp.cell(row=summary_row, column=8, value=round(total_savings / total_original * 100, 2))

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
```

- [ ] **Step 4: Run tests**

```bash
cd backend && python -m pytest tests/test_xlsx_optimizer.py -v
```
Expected: 8 tests pass

- [ ] **Step 5: Run full test suite**

```bash
cd backend && python -m pytest tests/ -q --tb=short
```
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add backend/app/utils/xlsx_optimizer.py backend/tests/test_xlsx_optimizer.py
git commit -m "feat: add xlsx_optimizer utility with parse/top-items/generate functions"
```

---

## Task 3: Add optimize endpoints to tasks router + endpoint tests

**Files:**
- Modify: `backend/app/routers/tasks.py` (add ~80 lines near end of file)
- Create: `backend/tests/test_optimize_endpoint.py`

Before editing, read `backend/app/routers/tasks.py` to find the correct insertion point and existing imports.

Key existing imports in tasks.py (already present):
- `from app.models.result import TaskResult`
- `from app.services.price_service import PriceService`
- `BackgroundTasks` from fastapi
- `get_current_user`, `get_db`, db session

- [ ] **Step 1: Write failing endpoint tests**

Create `backend/tests/test_optimize_endpoint.py`:

```python
"""Tests for POST /tasks/{task_id}/optimize/analyze and /optimize/run endpoints."""
import io
import uuid
import pytest
import pytest_asyncio
import openpyxl
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.models.task import Task
from app.models.result import TaskResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_smeta_xlsx_bytes() -> bytes:
    """Build a minimal valid smeta xlsx."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Смета"
    headers = [
        "№", "Тип", "Наименование", "Ед. изм.", "Кол-во",
        "Цена работы (за ед.)", "Цена материала (за ед.)",
        "Стоимость работ", "Стоимость материалов",
        "Итого без НДС", "НДС (20%)", "Итого с НДС",
        "Наименование в прайсе", "Источники", "Примечание",
    ]
    for col, h in enumerate(headers, start=1):
        ws.cell(row=1, column=col, value=h)
    ws.cell(row=2, column=2, value="Материал")
    ws.cell(row=2, column=3, value="Кирпич М150")
    ws.cell(row=2, column=4, value="шт")
    ws.cell(row=2, column=5, value=1000)
    ws.cell(row=2, column=7, value=10.0)
    ws.cell(row=2, column=10, value=10000.0)
    ws.cell(row=2, column=11, value=2000.0)
    ws.cell(row=2, column=12, value=12000.0)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


TASK_ID = "b1000000-0000-0000-0000-000000000001"


@pytest_asyncio.fixture
async def seed_optimize_task(db_session: AsyncSession):
    """Seed a task with an estimate slot result."""
    task = Task(
        id=TASK_ID,
        user_role="user",
        task_type="SMETA_FROM_LIST",
        status="completed",
        estimation_status="estimated",
        input_files=[{"name": "s.pdf", "mime_type": "application/pdf", "size_bytes": 10}],
        input_file_data=[{"name": "s.pdf", "mime_type": "application/pdf", "size_bytes": 10, "content_b64": "dGVzdA=="}],
        chat_history=[],
    )
    db_session.add(task)
    await db_session.flush()

    result = TaskResult(
        task_id=TASK_ID,
        slot="estimate",
        file_name="estimate.xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        file_data=_make_smeta_xlsx_bytes(),
    )
    db_session.add(result)
    await db_session.commit()
    yield
    await db_session.execute(text("DELETE FROM task_results WHERE task_id = :tid"), {"tid": TASK_ID})
    await db_session.execute(text("DELETE FROM tasks WHERE id = :tid"), {"tid": TASK_ID})
    await db_session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_returns_items(async_client: AsyncClient, user_token: str, seed_optimize_task):
    """POST /optimize/analyze returns 200 with items list."""
    resp = await async_client.post(
        f"/tasks/{TASK_ID}/optimize/analyze",
        json={"categories": ["work", "material"]},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total_analyzed" in data
    assert "total_selected" in data
    assert "coverage_pct" in data
    assert isinstance(data["items"], list)


@pytest.mark.asyncio
async def test_analyze_empty_slot_returns_404(async_client: AsyncClient, user_token: str, db_session: AsyncSession):
    """POST /optimize/analyze returns 404 when no estimate slot exists."""
    # Create task without estimate result
    no_slot_id = "c1000000-0000-0000-0000-000000000002"
    task = Task(
        id=no_slot_id,
        user_role="user",
        task_type="SMETA_FROM_LIST",
        status="completed",
        estimation_status="estimated",
        input_files=[],
        input_file_data=[],
        chat_history=[],
    )
    db_session.add(task)
    await db_session.commit()

    resp = await async_client.post(
        f"/tasks/{no_slot_id}/optimize/analyze",
        json={"categories": ["material"]},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 404

    await db_session.execute(text("DELETE FROM tasks WHERE id = :tid"), {"tid": no_slot_id})
    await db_session.commit()


@pytest.mark.asyncio
async def test_run_starts_background(async_client: AsyncClient, user_token: str, seed_optimize_task):
    """POST /optimize/run returns 200 with optimization_started status."""
    items = [
        {
            "row_index": 2,
            "name": "Кирпич М150",
            "type": "material",
            "quantity": 1000,
            "unit": "шт",
            "price_excl_vat": 10.0,
            "price_incl_vat": 12.0,
            "total": 12000.0,
        }
    ]
    resp = await async_client.post(
        f"/tasks/{TASK_ID}/optimize/run",
        json={"items": items, "prompt": "Тест", "categories": ["material"]},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "optimization_started"
    assert data["task_id"] == TASK_ID


@pytest.mark.asyncio
async def test_run_task_not_found(async_client: AsyncClient, user_token: str):
    """POST /optimize/run returns 404 for nonexistent task."""
    resp = await async_client.post(
        f"/tasks/nonexistent-id/optimize/run",
        json={"items": [], "prompt": "", "categories": ["material"]},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && python -m pytest tests/test_optimize_endpoint.py -v 2>&1 | head -30
```
Expected: 404 or route-not-found errors

- [ ] **Step 3: Read the end of tasks.py to find correct insertion point**

```bash
tail -60 backend/app/routers/tasks.py
```

- [ ] **Step 4: Add Pydantic models and endpoints to tasks.py**

At the top of `backend/app/routers/tasks.py`, the existing imports include `BackgroundTasks`. If not present, add it.

Add near the bottom of `backend/app/routers/tasks.py` (before the last router-level helper, after all existing endpoints):

```python
# ---------------------------------------------------------------------------
# Optimization endpoints
# ---------------------------------------------------------------------------

class OptimizeAnalyzeBody(BaseModel):
    categories: list[str] = ["work", "material"]
    other_description: Optional[str] = None


class OptimizeItem(BaseModel):
    row_index: int
    name: str
    type: str
    quantity: float
    unit: str
    price_excl_vat: float
    price_incl_vat: float
    total: float


class OptimizeRunBody(BaseModel):
    items: list[OptimizeItem]
    prompt: str = ""
    categories: list[str] = ["work", "material"]


@router.post("/{task_id}/optimize/analyze")
async def optimize_analyze(
    task_id: str,
    body: OptimizeAnalyzeBody,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Synchronously parse estimate xlsx and return top-70% items for user review."""
    from app.utils.xlsx_optimizer import parse_estimate_xlsx, get_top_items

    # Get estimate slot
    result = await db.execute(
        select(TaskResult).where(
            TaskResult.task_id == task_id,
            TaskResult.slot == "estimate",
        )
    )
    task_result = result.scalar_one_or_none()
    if task_result is None:
        raise HTTPException(status_code=404, detail="Файл сметы (слот estimate) не найден")

    try:
        items = parse_estimate_xlsx(task_result.file_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Не удалось разобрать xlsx: {e}")

    categories = body.categories or ["work", "material"]
    top_items = get_top_items(items, categories, threshold=0.7)

    total_cost = sum(it["total"] for it in items if it["type"] in categories)
    selected_cost = sum(it["total"] for it in top_items)
    coverage_pct = round(selected_cost / total_cost * 100, 1) if total_cost else 0.0

    return {
        "items": top_items,
        "total_analyzed": len(items),
        "total_selected": len(top_items),
        "coverage_pct": coverage_pct,
    }


async def _run_optimization_background(
    task_id: str,
    items: list[dict],
    prompt: str,
    estimate_bytes: bytes,
    session_factory,
):
    """Background task: search analogues and generate optimized xlsx."""
    import structlog as _structlog
    from app.utils.xlsx_optimizer import generate_optimized_xlsx
    from app.services.price_service import PriceService

    logger = _structlog.get_logger()

    async with session_factory() as db:
        try:
            task = await db.get(Task, task_id)
            if not task:
                return

            price_service = PriceService(db)
            optimization_results = []
            total = len(items)

            for i, item in enumerate(items):
                name = item["name"]
                item_type = item["type"]
                original_price = item["price_incl_vat"]

                task.progress_message = f"Обработано {i}/{total}: {name[:40]}"
                await db.commit()

                found_price = None
                source = "Не найдено"

                try:
                    if item_type == "work":
                        price_data = await price_service.find_work_price(name)
                    else:
                        price_data = await price_service.find_material_price(name)

                    if price_data and price_data.get("price"):
                        found_price = float(price_data["price"])
                        source = price_data.get("source", "Прайс-лист")
                except Exception as e:
                    logger.warning("price_search_failed", name=name, error=str(e))

                savings_abs = None
                savings_pct = None
                if found_price is not None and found_price < original_price:
                    savings_abs = round(original_price - found_price, 4)
                    savings_pct = round(savings_abs / original_price * 100, 2)
                elif found_price is not None and found_price >= original_price:
                    # Found but not cheaper — discard
                    found_price = None
                    source = "Не найдено (цена не ниже)"

                optimization_results.append({
                    "row_index": item["row_index"],
                    "name": name,
                    "original_price": original_price,
                    "new_price": found_price,
                    "source": source,
                    "savings_abs": savings_abs,
                    "savings_pct": savings_pct,
                    "has_vat": True,
                })

            optimized_bytes = generate_optimized_xlsx(estimate_bytes, optimization_results)

            # Save to optimized slot
            existing = await db.execute(
                select(TaskResult).where(
                    TaskResult.task_id == task_id,
                    TaskResult.slot == "optimized",
                )
            )
            existing_result = existing.scalar_one_or_none()
            if existing_result:
                existing_result.file_data = optimized_bytes
                existing_result.file_name = "optimized.xlsx"
            else:
                new_result = TaskResult(
                    task_id=task_id,
                    slot="optimized",
                    file_name="optimized.xlsx",
                    mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    file_data=optimized_bytes,
                )
                db.add(new_result)

            task.status = "completed"
            task.estimation_status = "optimized"
            task.progress_message = None
            await db.commit()
            logger.info("optimization_complete", task_id=task_id)

        except Exception as e:
            logger.error("optimization_failed", task_id=task_id, error=str(e))
            try:
                task = await db.get(Task, task_id)
                if task:
                    task.status = "failed"
                    task.error_message = str(e)
                    await db.commit()
            except Exception:
                pass


@router.post("/{task_id}/optimize/run")
async def optimize_run(
    task_id: str,
    body: OptimizeRunBody,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Start background optimization: search analogues and generate optimized xlsx."""
    # Verify task exists
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    # Get estimate slot
    result = await db.execute(
        select(TaskResult).where(
            TaskResult.task_id == task_id,
            TaskResult.slot == "estimate",
        )
    )
    task_result = result.scalar_one_or_none()
    if task_result is None:
        raise HTTPException(status_code=404, detail="Файл сметы (слот estimate) не найден")

    estimate_bytes = task_result.file_data

    task.status = "processing"
    task.estimation_status = "processing_optimization"
    task.progress_message = "Начинаем оптимизацию..."
    await db.commit()

    items_dicts = [item.model_dump() for item in body.items]

    from app.database import AsyncSessionLocal
    background_tasks.add_task(
        _run_optimization_background,
        task_id,
        items_dicts,
        body.prompt,
        estimate_bytes,
        AsyncSessionLocal,
    )

    return {"task_id": task_id, "status": "optimization_started"}
```

- [ ] **Step 5: Check that BackgroundTasks is imported in tasks.py**

Read the top of `backend/app/routers/tasks.py` (lines 1-30) to verify `BackgroundTasks` is imported. If not, add `BackgroundTasks` to the fastapi import line.

- [ ] **Step 6: Run endpoint tests**

```bash
cd backend && python -m pytest tests/test_optimize_endpoint.py -v
```
Expected: 4 tests pass

- [ ] **Step 7: Run full test suite**

```bash
cd backend && python -m pytest tests/ -q --tb=short
```
Expected: all tests pass

- [ ] **Step 8: Commit**

```bash
git add backend/app/routers/tasks.py backend/tests/test_optimize_endpoint.py
git commit -m "feat: add optimize/analyze and optimize/run endpoints"
```

---

## Task 4: Add OPTIMIZE_SMETA handler to task_processor.py

**Files:**
- Modify: `backend/app/services/task_processor.py`

Before editing, read the end of `task_processor.py` to understand the `process()` method's dispatch pattern and the `save_result()` / `update_status()` helper signatures.

- [ ] **Step 1: Read the process() dispatch block**

```bash
grep -n "OPTIMIZE_SMETA\|def process\|task_type" backend/app/services/task_processor.py | head -40
```

- [ ] **Step 2: Add OPTIMIZE_SMETA handler**

In `backend/app/services/task_processor.py`, inside the `process()` method's dispatch block (the `if/elif` chain on `task_type`), add:

```python
elif task_type == "OPTIMIZE_SMETA":
    await self._process_optimize_smeta()
```

Then add the handler method to the `TaskProcessor` class:

```python
async def _process_optimize_smeta(self):
    """Process OPTIMIZE_SMETA task: parse uploaded xlsx, find analogues, save optimized xlsx."""
    from app.utils.xlsx_optimizer import parse_estimate_xlsx, get_top_items, generate_optimized_xlsx
    from app.services.price_service import PriceService

    if not self.task.input_file_data:
        raise ValueError("Нет загруженного файла сметы")

    file_entry = self.task.input_file_data[0]
    import base64
    file_bytes = base64.b64decode(file_entry["content_b64"])

    await self.update_progress("Разбираю файл сметы...")
    items = parse_estimate_xlsx(file_bytes)
    top_items = get_top_items(items, categories=["work", "material"], threshold=0.7)

    price_service = PriceService(self.db)
    optimization_results = []
    total = len(top_items)

    for i, item in enumerate(top_items):
        name = item["name"]
        item_type = item["type"]
        original_price = item["price_incl_vat"]
        await self.update_progress(f"Поиск аналогов {i + 1}/{total}: {name[:40]}")

        found_price = None
        source = "Не найдено"
        try:
            if item_type == "work":
                price_data = await price_service.find_work_price(name)
            else:
                price_data = await price_service.find_material_price(name)
            if price_data and price_data.get("price"):
                found_price = float(price_data["price"])
                source = price_data.get("source", "Прайс-лист")
        except Exception:
            pass

        savings_abs = None
        savings_pct = None
        if found_price is not None and found_price < original_price:
            savings_abs = round(original_price - found_price, 4)
            savings_pct = round(savings_abs / original_price * 100, 2)
        elif found_price is not None:
            found_price = None
            source = "Не найдено (цена не ниже)"

        optimization_results.append({
            "row_index": item["row_index"],
            "name": name,
            "original_price": original_price,
            "new_price": found_price,
            "source": source,
            "savings_abs": savings_abs,
            "savings_pct": savings_pct,
            "has_vat": True,
        })

    await self.update_progress("Генерирую оптимизированный файл...")
    optimized_bytes = generate_optimized_xlsx(file_bytes, optimization_results)

    await self.save_result(
        file_name="optimized.xlsx",
        file_data=optimized_bytes,
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        slot="optimized",
    )
    await self.update_status("completed", estimation_status="optimized")
```

- [ ] **Step 3: Run full test suite**

```bash
cd backend && python -m pytest tests/ -q --tb=short
```
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/task_processor.py
git commit -m "feat: add OPTIMIZE_SMETA task type handler in task_processor"
```

---

## Task 5: Frontend types, API functions, TaskTypeSelector

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/tasks.ts`
- Modify: `frontend/src/components/TaskTypeSelector.tsx`

- [ ] **Step 1: Read current types/index.ts**

```bash
cat frontend/src/types/index.ts
```

- [ ] **Step 2: Update types/index.ts**

In `frontend/src/types/index.ts`:

1. Add `'OPTIMIZE_SMETA'` to the `TaskType` union:
```typescript
export type TaskType = 'LIST_FROM_TZ' | 'LIST_FROM_TZ_PROJECT' | 'RESEARCH_PROJECT' | 'LIST_FROM_PROJECT' | 'SMETA_FROM_GRAND_PROJECT' | 'SMETA_FROM_PROJECT' | 'SMETA_FROM_EDC_PROJECT' | 'SMETA_FROM_LIST' | 'SCAN_TO_EXCEL' | 'COMPARE_PROJECT_SMETA' | 'OPTIMIZE_SMETA';
```

2. Add `'processing_optimization'` to `EstimationStatus`:
```typescript
export type EstimationStatus = 'unestimated' | 'estimated' | 'processing_optimization' | 'optimized' | 'not_applicable';
```

- [ ] **Step 3: Read current api/tasks.ts**

```bash
cat frontend/src/api/tasks.ts
```

- [ ] **Step 4: Update api/tasks.ts — add interfaces and functions**

At the end of `frontend/src/api/tasks.ts`, add:

```typescript
// ---------------------------------------------------------------------------
// Optimization
// ---------------------------------------------------------------------------

export interface OptimizeItem {
  row_index: number;
  name: string;
  type: string;
  quantity: number;
  unit: string;
  price_excl_vat: number;
  price_incl_vat: number;
  total: number;
  selected?: boolean;
}

export interface AnalyzeOptimizeResponse {
  items: OptimizeItem[];
  total_analyzed: number;
  total_selected: number;
  coverage_pct: number;
}

export async function analyzeOptimize(
  taskId: string,
  categories: string[],
  otherDescription?: string
): Promise<AnalyzeOptimizeResponse> {
  const res = await apiClient.post(`/tasks/${taskId}/optimize/analyze`, {
    categories,
    other_description: otherDescription ?? null,
  });
  return res.data;
}

export async function runOptimize(
  taskId: string,
  items: OptimizeItem[],
  prompt: string,
  categories: string[]
): Promise<{ task_id: string; status: string }> {
  const res = await apiClient.post(`/tasks/${taskId}/optimize/run`, {
    items,
    prompt,
    categories,
  });
  return res.data;
}
```

- [ ] **Step 5: Read TaskTypeSelector.tsx**

```bash
cat frontend/src/components/TaskTypeSelector.tsx
```

- [ ] **Step 6: Add OPTIMIZE_SMETA to TaskTypeSelector**

In `frontend/src/components/TaskTypeSelector.tsx`, find the `TASK_TYPES` array (or similar constant) and add:

```typescript
{ value: 'OPTIMIZE_SMETA', label: 'Оптимизация сметы', hint: 'Загрузите xlsx сметы — система найдёт аналоги по более низкой цене' },
```

Also add to `TASK_TYPE_LABELS` in `frontend/src/types/index.ts` if that map exists there:
```typescript
OPTIMIZE_SMETA: 'Оптимизация сметы',
```

- [ ] **Step 7: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```
Expected: no errors (or only pre-existing ones)

- [ ] **Step 8: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/tasks.ts frontend/src/components/TaskTypeSelector.tsx
git commit -m "feat: add OPTIMIZE_SMETA type and analyzeOptimize/runOptimize API functions"
```

---

## Task 6: Create OptimizeModal.tsx (4-step wizard)

**Files:**
- Create: `frontend/src/components/OptimizeModal.tsx`

The modal is a 4-step wizard:
- Step 1: Category checkboxes → `[Анализировать]`
- Step 2: Editable table of top-70% items + prompt textarea → `[Запустить поиск цен]`
- Step 3: Progress polling (every 2s via `getTaskStatus`) + animated bar
- Step 4: Results summary + `[Скачать xlsx]` / `[Закрыть]`

Download URL: `GET /tasks/{id}/files/optimized/download` — use the same `apiClient` base URL.

- [ ] **Step 1: Read existing modal patterns**

```bash
ls frontend/src/components/
```
Look for an existing modal component to understand the overlay/backdrop pattern used in this codebase.

- [ ] **Step 2: Create OptimizeModal.tsx**

Create `frontend/src/components/OptimizeModal.tsx`:

```tsx
import React, { useState, useEffect, useRef } from 'react';
import { analyzeOptimize, runOptimize, getTaskStatus, OptimizeItem } from '../api/tasks';
import apiClient from '../api/client';

interface OptimizeModalProps {
  taskId: string;
  onClose: () => void;
}

type Step = 1 | 2 | 3 | 4;

const CATEGORIES = [
  { value: 'work', label: 'Работы' },
  { value: 'material', label: 'Материалы' },
  { value: 'extra', label: 'Дополнительные расходы' },
];

const DEFAULT_PROMPT =
  'Ищи аналоги с более низкой ценой. Предпочитай проверенных поставщиков. Указывай источник (URL или название поставщика).';

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency: 'RUB',
    maximumFractionDigits: 0,
  }).format(value);
}

const OptimizeModal: React.FC<OptimizeModalProps> = ({ taskId, onClose }) => {
  const [step, setStep] = useState<Step>(1);
  const [categories, setCategories] = useState<string[]>(['work', 'material']);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState('');
  const [items, setItems] = useState<OptimizeItem[]>([]);
  const [totalAnalyzed, setTotalAnalyzed] = useState(0);
  const [coveragePct, setCoveragePct] = useState(0);
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
  const [progressMessage, setProgressMessage] = useState('Начинаем оптимизацию...');
  const [runError, setRunError] = useState('');
  const [timedOut, setTimedOut] = useState(false);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number>(0);
  const TIMEOUT_MS = 5 * 60 * 1000;

  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, []);

  function toggleCategory(value: string) {
    setCategories((prev) =>
      prev.includes(value) ? prev.filter((c) => c !== value) : [...prev, value]
    );
  }

  function toggleItem(rowIndex: number) {
    setItems((prev) =>
      prev.map((it) =>
        it.row_index === rowIndex ? { ...it, selected: !it.selected } : it
      )
    );
  }

  async function handleAnalyze() {
    if (categories.length === 0) return;
    setAnalyzing(true);
    setAnalyzeError('');
    try {
      const data = await analyzeOptimize(taskId, categories);
      setItems(data.items);
      setTotalAnalyzed(data.total_analyzed);
      setCoveragePct(data.coverage_pct);
      setStep(2);
    } catch (e: any) {
      setAnalyzeError(e?.response?.data?.detail ?? 'Ошибка анализа');
    } finally {
      setAnalyzing(false);
    }
  }

  async function handleRunOptimize() {
    const selectedItems = items.filter((it) => it.selected !== false);
    if (selectedItems.length === 0) return;
    setRunError('');
    try {
      await runOptimize(taskId, selectedItems, prompt, categories);
      setStep(3);
      startTimeRef.current = Date.now();
      pollingRef.current = setInterval(async () => {
        if (Date.now() - startTimeRef.current > TIMEOUT_MS) {
          clearInterval(pollingRef.current!);
          setTimedOut(true);
          return;
        }
        try {
          const status = await getTaskStatus(taskId);
          if (status.progress_message) {
            setProgressMessage(status.progress_message);
          }
          if (status.estimation_status === 'optimized' || status.status === 'completed') {
            clearInterval(pollingRef.current!);
            setStep(4);
          } else if (status.status === 'failed') {
            clearInterval(pollingRef.current!);
            setRunError(status.error_message ?? 'Ошибка оптимизации');
          }
        } catch {
          // keep polling
        }
      }, 2000);
    } catch (e: any) {
      setRunError(e?.response?.data?.detail ?? 'Ошибка запуска оптимизации');
    }
  }

  async function handleDownload() {
    try {
      const response = await apiClient.get(`/tasks/${taskId}/files/optimized/download`, {
        responseType: 'blob',
      });
      const url = URL.createObjectURL(response.data);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'optimized.xlsx';
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // silently ignore download errors
    }
  }

  const selectedItems = items.filter((it) => it.selected !== false);
  const totalCost = selectedItems.reduce((s, it) => s + it.total, 0);

  return (
    <div
      style={{
        position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.5)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{
        backgroundColor: '#fff', borderRadius: '16px', padding: '32px',
        width: '700px', maxWidth: '95vw', maxHeight: '85vh',
        overflowY: 'auto', position: 'relative',
      }}>
        <button
          onClick={onClose}
          style={{ position: 'absolute', top: '16px', right: '16px', background: 'none', border: 'none', fontSize: '20px', cursor: 'pointer', color: '#94a3b8' }}
        >
          ×
        </button>

        {/* Step indicator */}
        <div style={{ display: 'flex', gap: '8px', marginBottom: '24px' }}>
          {([1, 2, 3, 4] as Step[]).map((s) => (
            <div
              key={s}
              style={{
                width: '28px', height: '28px', borderRadius: '50%',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: '12px', fontWeight: 600,
                backgroundColor: s === step ? '#2563eb' : s < step ? '#bbf7d0' : '#f1f5f9',
                color: s === step ? '#fff' : s < step ? '#15803d' : '#94a3b8',
              }}
            >
              {s}
            </div>
          ))}
          <span style={{ marginLeft: '8px', fontSize: '14px', color: '#64748b', alignSelf: 'center' }}>
            {step === 1 && 'Выбор категорий'}
            {step === 2 && 'Предварительный анализ'}
            {step === 3 && 'Поиск аналогов...'}
            {step === 4 && 'Результат'}
          </span>
        </div>

        {/* Step 1 */}
        {step === 1 && (
          <div>
            <h3 style={{ margin: '0 0 16px', fontSize: '18px', fontWeight: 700 }}>
              ⚡ Оптимизация сметы
            </h3>
            <p style={{ color: '#64748b', fontSize: '14px', marginBottom: '20px' }}>
              Выберите категории позиций для поиска аналогов по более низкой цене.
            </p>
            {CATEGORIES.map((cat) => (
              <label
                key={cat.value}
                style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px', cursor: 'pointer', fontSize: '15px' }}
              >
                <input
                  type="checkbox"
                  checked={categories.includes(cat.value)}
                  onChange={() => toggleCategory(cat.value)}
                  style={{ width: '16px', height: '16px', cursor: 'pointer' }}
                />
                {cat.label}
              </label>
            ))}
            {analyzeError && (
              <p style={{ color: '#dc2626', fontSize: '13px', marginTop: '8px' }}>{analyzeError}</p>
            )}
            <button
              onClick={handleAnalyze}
              disabled={analyzing || categories.length === 0}
              style={{
                marginTop: '20px', padding: '10px 24px', backgroundColor: '#2563eb',
                color: '#fff', border: 'none', borderRadius: '8px', cursor: analyzing ? 'not-allowed' : 'pointer',
                fontWeight: 600, fontSize: '14px', opacity: analyzing ? 0.7 : 1,
              }}
            >
              {analyzing ? 'Анализирую...' : 'Анализировать'}
            </button>
          </div>
        )}

        {/* Step 2 */}
        {step === 2 && (
          <div>
            <h3 style={{ margin: '0 0 4px', fontSize: '18px', fontWeight: 700 }}>
              Предварительный анализ
            </h3>
            <p style={{ color: '#64748b', fontSize: '13px', marginBottom: '16px' }}>
              Из {totalAnalyzed} позиций выбрано {selectedItems.length} наиболее дорогостоящих
              (покрытие {coveragePct}%). Снимите галочку с позиций, которые не нужно оптимизировать.
            </p>

            <div style={{ overflowX: 'auto', marginBottom: '16px' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
                <thead>
                  <tr style={{ backgroundColor: '#f8fafc' }}>
                    <th style={thStyle}></th>
                    <th style={thStyle}>Наименование</th>
                    <th style={thStyle}>Тип</th>
                    <th style={{ ...thStyle, textAlign: 'right' }}>Стоимость</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((it) => (
                    <tr key={it.row_index} style={{ borderBottom: '1px solid #f1f5f9', opacity: it.selected === false ? 0.4 : 1 }}>
                      <td style={{ padding: '8px 4px', textAlign: 'center' }}>
                        <input
                          type="checkbox"
                          checked={it.selected !== false}
                          onChange={() => toggleItem(it.row_index)}
                          style={{ cursor: 'pointer' }}
                        />
                      </td>
                      <td style={{ padding: '8px 4px', color: '#1e293b' }}>{it.name}</td>
                      <td style={{ padding: '8px 4px', color: '#64748b' }}>
                        {it.type === 'work' ? 'Работа' : it.type === 'material' ? 'Материал' : it.type}
                      </td>
                      <td style={{ padding: '8px 4px', textAlign: 'right', fontWeight: 500 }}>
                        {formatCurrency(it.total)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div style={{ marginBottom: '16px' }}>
              <label style={{ fontSize: '13px', fontWeight: 600, color: '#374151', display: 'block', marginBottom: '6px' }}>
                Инструкции для поиска (необязательно)
              </label>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={3}
                style={{ width: '100%', padding: '8px 12px', border: '1px solid #e2e8f0', borderRadius: '8px', fontSize: '13px', resize: 'vertical', boxSizing: 'border-box' }}
              />
            </div>

            {runError && (
              <p style={{ color: '#dc2626', fontSize: '13px', marginBottom: '8px' }}>{runError}</p>
            )}

            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                onClick={() => setStep(1)}
                style={{ padding: '10px 18px', background: 'transparent', border: '1px solid #e2e8f0', borderRadius: '8px', cursor: 'pointer', fontSize: '14px', color: '#64748b' }}
              >
                ← Назад
              </button>
              <button
                onClick={handleRunOptimize}
                disabled={selectedItems.length === 0}
                style={{
                  padding: '10px 24px', backgroundColor: '#2563eb', color: '#fff',
                  border: 'none', borderRadius: '8px', fontWeight: 600, fontSize: '14px',
                  cursor: selectedItems.length === 0 ? 'not-allowed' : 'pointer',
                  opacity: selectedItems.length === 0 ? 0.7 : 1,
                }}
              >
                Запустить поиск цен ({selectedItems.length} позиций)
              </button>
            </div>
          </div>
        )}

        {/* Step 3 */}
        {step === 3 && (
          <div style={{ textAlign: 'center', padding: '20px 0' }}>
            <h3 style={{ margin: '0 0 16px', fontSize: '18px', fontWeight: 700 }}>
              Поиск аналогов...
            </h3>
            {timedOut ? (
              <p style={{ color: '#dc2626', fontSize: '14px' }}>Превышено время ожидания (5 минут). Проверьте статус задачи позже.</p>
            ) : runError ? (
              <p style={{ color: '#dc2626', fontSize: '14px' }}>{runError}</p>
            ) : (
              <>
                <p style={{ color: '#64748b', fontSize: '14px', marginBottom: '20px' }}>
                  {progressMessage}
                </p>
                {/* Animated progress bar */}
                <div style={{ width: '100%', height: '6px', backgroundColor: '#e2e8f0', borderRadius: '3px', overflow: 'hidden', marginBottom: '8px' }}>
                  <div
                    style={{
                      height: '100%', backgroundColor: '#2563eb', borderRadius: '3px',
                      width: '40%',
                      animation: 'progress-slide 1.5s ease-in-out infinite',
                    }}
                  />
                </div>
                <style>{`
                  @keyframes progress-slide {
                    0% { transform: translateX(-100%); width: 40%; }
                    50% { transform: translateX(100%); width: 60%; }
                    100% { transform: translateX(250%); width: 40%; }
                  }
                `}</style>
                <p style={{ fontSize: '12px', color: '#94a3b8' }}>Это может занять несколько минут</p>
              </>
            )}
          </div>
        )}

        {/* Step 4 */}
        {step === 4 && (
          <div>
            <h3 style={{ margin: '0 0 16px', fontSize: '18px', fontWeight: 700, color: '#15803d' }}>
              Оптимизация завершена
            </h3>
            <p style={{ color: '#64748b', fontSize: '14px', marginBottom: '24px' }}>
              Оптимизированный файл сметы готов. Скачайте xlsx с выделенными аналогами и листом сравнения.
            </p>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                onClick={handleDownload}
                style={{
                  padding: '10px 24px', backgroundColor: '#15803d', color: '#fff',
                  border: 'none', borderRadius: '8px', fontWeight: 600, fontSize: '14px', cursor: 'pointer',
                }}
              >
                Скачать xlsx
              </button>
              <button
                onClick={onClose}
                style={{ padding: '10px 18px', background: 'transparent', border: '1px solid #e2e8f0', borderRadius: '8px', cursor: 'pointer', fontSize: '14px', color: '#64748b' }}
              >
                Закрыть
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

const thStyle: React.CSSProperties = {
  padding: '8px 4px',
  textAlign: 'left',
  fontWeight: 600,
  color: '#64748b',
  borderBottom: '1px solid #e2e8f0',
  fontSize: '12px',
  textTransform: 'uppercase',
  letterSpacing: '0.03em',
};

export default OptimizeModal;
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```
Expected: no new errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/OptimizeModal.tsx
git commit -m "feat: add OptimizeModal 4-step wizard component"
```

---

## Task 7: Wire OptimizeModal into ProjectDetail.tsx

**Files:**
- Modify: `frontend/src/pages/ProjectDetail.tsx`

The "Оптимизировать" button appears in the task row when `task.estimation_status === 'estimated'`. Clicking opens the modal. On close, `loadProject()` is called to refresh task list.

- [ ] **Step 1: Read current ProjectDetail.tsx (already known)**

The file is at `frontend/src/pages/ProjectDetail.tsx`. State already has: `project`, `loading`, `error`, `editing`, `exporting`. Needs new state: `optimizingTaskId`.

- [ ] **Step 2: Add import and state**

At the top of `ProjectDetail.tsx`, add import:
```tsx
import OptimizeModal from '../components/OptimizeModal';
```

In the component body, add state (after existing state declarations):
```tsx
const [optimizingTaskId, setOptimizingTaskId] = useState<string | null>(null);
```

Also add `'processing_optimization'` to `ESTIMATION_LABELS`:
```tsx
const ESTIMATION_LABELS: Record<string, string> = {
  unestimated: 'Не рассчитано',
  estimated: 'Рассчитано',
  processing_optimization: 'Оптимизируется',
  optimized: 'Оптимизировано',
  not_applicable: '—',
};
```

And to `ESTIMATION_COLORS`:
```tsx
processing_optimization: { bg: '#eff6ff', text: '#2563eb' },
```

- [ ] **Step 3: Add the Оптимизировать button in the task row**

Inside the task map in ProjectDetail.tsx, the task row `<div>` has an `onClick` for navigation. The button must stop propagation to prevent navigation.

Find the task row's right-side `<div>` (the one with cost + estimation badge), and add before the cost badge:

```tsx
{task.estimation_status === 'estimated' && (
  <button
    onClick={(e) => {
      e.stopPropagation();
      setOptimizingTaskId(task.id);
    }}
    style={{
      padding: '4px 12px',
      backgroundColor: '#eff6ff',
      color: '#2563eb',
      border: '1px solid #bfdbfe',
      borderRadius: '8px',
      cursor: 'pointer',
      fontSize: '12px',
      fontWeight: 600,
    }}
  >
    Оптимизировать
  </button>
)}
```

- [ ] **Step 4: Mount OptimizeModal at the bottom of the component return**

Inside the main `<Layout>` return, just before the closing `</Layout>` tag:

```tsx
{optimizingTaskId && (
  <OptimizeModal
    taskId={optimizingTaskId}
    onClose={() => {
      setOptimizingTaskId(null);
      loadProject();
    }}
  />
)}
```

- [ ] **Step 5: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```
Expected: no errors

- [ ] **Step 6: Run backend tests one final time**

```bash
cd backend && python -m pytest tests/ -q --tb=short
```
Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/ProjectDetail.tsx
git commit -m "feat: add Оптимизировать button and OptimizeModal to ProjectDetail"
```

---

## Final: verify and push

- [ ] **Step 1: Run full backend test suite**

```bash
cd backend && python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected: all tests pass (12 new tests + all existing)

- [ ] **Step 2: TypeScript final check**

```bash
cd frontend && npx tsc --noEmit
```
Expected: clean

- [ ] **Step 3: Push to main**

```bash
git push origin main
```
