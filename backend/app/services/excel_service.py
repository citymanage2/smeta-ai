import io
from typing import Any, Optional
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import structlog

logger = structlog.get_logger()

HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
BOLD_FONT = Font(bold=True, size=11)
NORMAL_FONT = Font(size=11)
TOTAL_FILL = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")

THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)


def _style_header_row(ws, row: int, col_count: int) -> None:
    for col in range(1, col_count + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER


def _style_data_row(ws, row: int, col_count: int, bold: bool = False) -> None:
    for col in range(1, col_count + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = BOLD_FONT if bold else NORMAL_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.border = THIN_BORDER


def _auto_fit_columns(ws, min_width: int = 10, max_width: int = 60) -> None:
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            if cell.value:
                max_len = max(max_len, len(str(cell.value)))
        adjusted = min(max(max_len + 2, min_width), max_width)
        ws.column_dimensions[col_letter].width = adjusted


def generate_list(items: list, changes_summary: Optional[str] = None) -> bytes:
    """
    Generate Excel file with list of works/materials.
    items: list of dicts with keys: type, name, unit, quantity
    changes_summary: optional explanatory text about deviations from TZ
    """
    wb = openpyxl.Workbook()

    # Sheet 1: Перечень (All items)
    ws_all = wb.active
    ws_all.title = "Перечень"

    headers_all = ["№", "Тип", "Наименование", "Ед. изм.", "Кол-во"]
    for col, h in enumerate(headers_all, start=1):
        ws_all.cell(row=1, column=col, value=h)
    _style_header_row(ws_all, 1, len(headers_all))

    ws_all.row_dimensions[1].height = 30

    for i, item in enumerate(items, start=1):
        row = i + 1
        ws_all.cell(row=row, column=1, value=i)
        ws_all.cell(row=row, column=2, value=item.get("type", ""))
        ws_all.cell(row=row, column=3, value=item.get("name", ""))
        ws_all.cell(row=row, column=4, value=item.get("unit", ""))
        qty = item.get("quantity")
        ws_all.cell(row=row, column=5, value=qty)
        _style_data_row(ws_all, row, len(headers_all))

    _auto_fit_columns(ws_all)
    ws_all.freeze_panes = "A2"

    # Sheet 2: Работы
    works = [it for it in items if it.get("type", "").lower() in ("работа", "work", "работы")]
    ws_works = wb.create_sheet("Работы")
    headers_works = ["№", "Наименование", "Ед. изм.", "Кол-во"]
    for col, h in enumerate(headers_works, start=1):
        ws_works.cell(row=1, column=col, value=h)
    _style_header_row(ws_works, 1, len(headers_works))
    ws_works.row_dimensions[1].height = 30

    for i, item in enumerate(works, start=1):
        row = i + 1
        ws_works.cell(row=row, column=1, value=i)
        ws_works.cell(row=row, column=2, value=item.get("name", ""))
        ws_works.cell(row=row, column=3, value=item.get("unit", ""))
        ws_works.cell(row=row, column=4, value=item.get("quantity"))
        _style_data_row(ws_works, row, len(headers_works))

    _auto_fit_columns(ws_works)
    ws_works.freeze_panes = "A2"

    # Sheet 3: Материалы
    materials = [it for it in items if it.get("type", "").lower() in ("материал", "material", "материалы")]
    ws_mats = wb.create_sheet("Материалы")
    headers_mats = ["№", "Наименование", "Ед. изм.", "Кол-во"]
    for col, h in enumerate(headers_mats, start=1):
        ws_mats.cell(row=1, column=col, value=h)
    _style_header_row(ws_mats, 1, len(headers_mats))
    ws_mats.row_dimensions[1].height = 30

    for i, item in enumerate(materials, start=1):
        row = i + 1
        ws_mats.cell(row=row, column=1, value=i)
        ws_mats.cell(row=row, column=2, value=item.get("name", ""))
        ws_mats.cell(row=row, column=3, value=item.get("unit", ""))
        ws_mats.cell(row=row, column=4, value=item.get("quantity"))
        _style_data_row(ws_mats, row, len(headers_mats))

    _auto_fit_columns(ws_mats)
    ws_mats.freeze_panes = "A2"

    # Sheet 4: Пояснительная записка
    ws_note = wb.create_sheet("Пояснительная записка")
    note_text = (
        changes_summary
        if changes_summary
        else "Перечень соответствует ТЗ, дополнений не требуется"
    )
    ws_note.cell(row=1, column=1, value="Пояснительная записка").font = BOLD_FONT
    ws_note.cell(row=1, column=1).fill = HEADER_FILL
    ws_note.cell(row=1, column=1).font = HEADER_FONT
    ws_note.row_dimensions[1].height = 30

    # Write text wrapped across rows (split by newline for readability)
    for row_offset, line in enumerate(note_text.splitlines(), start=2):
        cell = ws_note.cell(row=row_offset, column=1, value=line)
        cell.font = NORMAL_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="top")

    ws_note.column_dimensions["A"].width = 120
    ws_note.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def generate_list_project(items: list, changes_summary: Optional[str] = None) -> bytes:
    """
    Generate Excel for LIST_FROM_TZ_PROJECT tasks.
    Same 3 item sheets as generate_list, plus a 2-section "Пояснительная записка" sheet
    that splits changes_summary at "Раздел 2".
    """
    wb = openpyxl.Workbook()

    # Sheet 1: Перечень (All items) — includes section column
    ws_all = wb.active
    ws_all.title = "Перечень"

    headers_all = ["№", "Тип", "Раздел", "Наименование", "Ед. изм.", "Кол-во", "Примечание"]
    for col, h in enumerate(headers_all, start=1):
        ws_all.cell(row=1, column=col, value=h)
    _style_header_row(ws_all, 1, len(headers_all))
    ws_all.row_dimensions[1].height = 30

    for i, item in enumerate(items, start=1):
        row = i + 1
        ws_all.cell(row=row, column=1, value=i)
        ws_all.cell(row=row, column=2, value=item.get("type", ""))
        ws_all.cell(row=row, column=3, value=item.get("section", ""))
        ws_all.cell(row=row, column=4, value=item.get("name", ""))
        ws_all.cell(row=row, column=5, value=item.get("unit", ""))
        ws_all.cell(row=row, column=6, value=item.get("quantity"))
        ws_all.cell(row=row, column=7, value=item.get("notes", ""))
        _style_data_row(ws_all, row, len(headers_all))

    _auto_fit_columns(ws_all)
    ws_all.freeze_panes = "A2"

    # Sheet 2: Работы
    works = [it for it in items if it.get("type", "").lower() in ("работа", "work", "работы")]
    ws_works = wb.create_sheet("Работы")
    headers_works = ["№", "Раздел", "Наименование", "Ед. изм.", "Кол-во", "Примечание"]
    for col, h in enumerate(headers_works, start=1):
        ws_works.cell(row=1, column=col, value=h)
    _style_header_row(ws_works, 1, len(headers_works))
    ws_works.row_dimensions[1].height = 30

    for i, item in enumerate(works, start=1):
        row = i + 1
        ws_works.cell(row=row, column=1, value=i)
        ws_works.cell(row=row, column=2, value=item.get("section", ""))
        ws_works.cell(row=row, column=3, value=item.get("name", ""))
        ws_works.cell(row=row, column=4, value=item.get("unit", ""))
        ws_works.cell(row=row, column=5, value=item.get("quantity"))
        ws_works.cell(row=row, column=6, value=item.get("notes", ""))
        _style_data_row(ws_works, row, len(headers_works))

    _auto_fit_columns(ws_works)
    ws_works.freeze_panes = "A2"

    # Sheet 3: Материалы
    materials = [it for it in items if it.get("type", "").lower() in ("материал", "material", "материалы")]
    ws_mats = wb.create_sheet("Материалы")
    headers_mats = ["№", "Раздел", "Наименование", "Ед. изм.", "Кол-во", "Примечание"]
    for col, h in enumerate(headers_mats, start=1):
        ws_mats.cell(row=1, column=col, value=h)
    _style_header_row(ws_mats, 1, len(headers_mats))
    ws_mats.row_dimensions[1].height = 30

    for i, item in enumerate(materials, start=1):
        row = i + 1
        ws_mats.cell(row=row, column=1, value=i)
        ws_mats.cell(row=row, column=2, value=item.get("section", ""))
        ws_mats.cell(row=row, column=3, value=item.get("name", ""))
        ws_mats.cell(row=row, column=4, value=item.get("unit", ""))
        ws_mats.cell(row=row, column=5, value=item.get("quantity"))
        ws_mats.cell(row=row, column=6, value=item.get("notes", ""))
        _style_data_row(ws_mats, row, len(headers_mats))

    _auto_fit_columns(ws_mats)
    ws_mats.freeze_panes = "A2"

    # Sheet 4: Пояснительная записка (two sections)
    ws_note = wb.create_sheet("Пояснительная записка")
    ws_note.column_dimensions["A"].width = 120

    FALLBACK = "Документация соответствует друг другу, дополнений не требуется"

    if not changes_summary:
        # No summary — write fallback under a single header
        _write_note_section(ws_note, 1, "Пояснительная записка", FALLBACK)
    else:
        # Split on "Раздел 2" (case-insensitive, strip surrounding whitespace)
        import re
        split_match = re.search(r"(?i)раздел\s*2", changes_summary)
        if split_match:
            part1 = changes_summary[: split_match.start()].strip()
            part2 = changes_summary[split_match.start() :].strip()
        else:
            part1 = changes_summary.strip()
            part2 = ""

        current_row = _write_note_section(
            ws_note, 1,
            "Раздел 1 — Сравнение ТЗ и проекта",
            part1 or FALLBACK,
        )
        if part2:
            _write_note_section(
                ws_note, current_row + 1,
                "Раздел 2 — Изменения по нормативной базе",
                part2,
            )

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _write_note_section(ws, start_row: int, title: str, body: str) -> int:
    """
    Write a bold section header at start_row, then body lines below it.
    Returns the last row written.
    """
    # Section header
    header_cell = ws.cell(row=start_row, column=1, value=title)
    header_cell.font = BOLD_FONT
    header_cell.fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    header_cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[start_row].height = 22

    current_row = start_row + 1
    for line in body.splitlines():
        cell = ws.cell(row=current_row, column=1, value=line)
        cell.font = NORMAL_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        current_row += 1

    return current_row


def generate_smeta_from_tz_project(
    smeta_items: list,
    list_items: list,
    changes_summary: Optional[str] = None,
) -> bytes:
    """
    Generate 5-sheet Excel for SMETA_FROM_TZ_PROJECT tasks.
    Sheet 1 "Смета"                      — priced estimate (smeta_items from Stage 2)
    Sheet 2 "Перечень работ и материалов" — all items from Stage 1
    Sheet 3 "Перечень работ"              — works from Stage 1
    Sheet 4 "Перечень материалов"         — materials from Stage 1
    Sheet 5 "Пояснительная записка"       — changes_summary (two sections)
    """
    VAT_RATE = 0.20
    wb = openpyxl.Workbook()

    # ── Sheet 1: Смета (priced estimate, Stage 2 items) ────────────────────
    ws_smeta = wb.active
    ws_smeta.title = "Смета"

    smeta_headers = [
        "№", "Тип", "Наименование", "Ед. изм.", "Кол-во",
        "Цена работы (за ед.)", "Цена материала (за ед.)",
        "Стоимость работ", "Стоимость материалов",
        "Итого без НДС", "НДС (20%)", "Итого с НДС",
        "Наименование в прайсе", "Источники", "Примечание",
    ]
    for col, h in enumerate(smeta_headers, start=1):
        ws_smeta.cell(row=1, column=col, value=h)
    _style_header_row(ws_smeta, 1, len(smeta_headers))
    ws_smeta.row_dimensions[1].height = 40

    for i, item in enumerate(smeta_items, start=1):
        row = i + 1
        qty = item.get("quantity") or 0
        wp = item.get("work_price") or 0
        mp = item.get("material_price") or 0
        work_total = qty * wp
        mat_total = qty * mp
        subtotal = work_total + mat_total
        vat = subtotal * VAT_RATE
        total = subtotal + vat

        ws_smeta.cell(row=row, column=1, value=i)
        ws_smeta.cell(row=row, column=2, value=item.get("type", ""))
        ws_smeta.cell(row=row, column=3, value=item.get("name", ""))
        ws_smeta.cell(row=row, column=4, value=item.get("unit", ""))
        ws_smeta.cell(row=row, column=5, value=qty)
        ws_smeta.cell(row=row, column=6, value=wp if wp else None)
        ws_smeta.cell(row=row, column=7, value=mp if mp else None)
        ws_smeta.cell(row=row, column=8, value=work_total if work_total else None)
        ws_smeta.cell(row=row, column=9, value=mat_total if mat_total else None)
        ws_smeta.cell(row=row, column=10, value=subtotal if subtotal else None)
        ws_smeta.cell(row=row, column=11, value=vat if vat else None)
        ws_smeta.cell(row=row, column=12, value=total if total else None)
        ws_smeta.cell(row=row, column=13, value=item.get("price_list_name", "") or "")
        ws_smeta.cell(row=row, column=14, value=item.get("sources", "") or "")
        ws_smeta.cell(row=row, column=15, value=item.get("notes", ""))
        _style_data_row(ws_smeta, row, len(smeta_headers))

    # Totals row
    if smeta_items:
        total_row = len(smeta_items) + 2
        ws_smeta.cell(row=total_row, column=1, value="ИТОГО")
        ws_smeta.merge_cells(start_row=total_row, start_column=1, end_row=total_row, end_column=7)
        data_end = len(smeta_items) + 1
        for col in [8, 9, 10, 11, 12]:
            cl = get_column_letter(col)
            ws_smeta.cell(row=total_row, column=col,
                          value=f"=SUM({cl}2:{cl}{data_end})")
            ws_smeta.cell(row=total_row, column=col).number_format = '#,##0.00'
        for col in range(1, len(smeta_headers) + 1):
            c = ws_smeta.cell(row=total_row, column=col)
            c.fill = TOTAL_FILL
            c.font = BOLD_FONT
            c.border = THIN_BORDER

    for col in [6, 7, 8, 9, 10, 11, 12]:
        for row in range(2, len(smeta_items) + 2):
            ws_smeta.cell(row=row, column=col).number_format = '#,##0.00'

    _auto_fit_columns(ws_smeta)
    ws_smeta.freeze_panes = "A2"

    # ── Sheets 2-4: Перечень from Stage 1 ──────────────────────────────────
    list_headers_all = ["№", "Тип", "Раздел", "Наименование", "Ед. изм.", "Кол-во", "Примечание"]
    list_headers_sub = ["№", "Раздел", "Наименование", "Ед. изм.", "Кол-во", "Примечание"]

    def _write_list_sheet(ws, rows, headers, include_type=False):
        for col, h in enumerate(headers, start=1):
            ws.cell(row=1, column=col, value=h)
        _style_header_row(ws, 1, len(headers))
        ws.row_dimensions[1].height = 30
        for i, item in enumerate(rows, start=1):
            r = i + 1
            if include_type:
                vals = [
                    i,
                    item.get("type", ""),
                    item.get("section", ""),
                    item.get("name", ""),
                    item.get("unit", ""),
                    item.get("quantity"),
                    item.get("notes", ""),
                ]
            else:
                vals = [
                    i,
                    item.get("section", ""),
                    item.get("name", ""),
                    item.get("unit", ""),
                    item.get("quantity"),
                    item.get("notes", ""),
                ]
            for col, val in enumerate(vals, start=1):
                ws.cell(row=r, column=col, value=val)
            _style_data_row(ws, r, len(headers))
        _auto_fit_columns(ws)
        ws.freeze_panes = "A2"

    ws_all = wb.create_sheet("Перечень работ и материалов")
    _write_list_sheet(ws_all, list_items, list_headers_all, include_type=True)

    works = [it for it in list_items if it.get("type", "").lower() in ("работа", "work", "работы")]
    ws_works = wb.create_sheet("Перечень работ")
    _write_list_sheet(ws_works, works, list_headers_sub)

    materials = [it for it in list_items if it.get("type", "").lower() in ("материал", "material", "материалы")]
    ws_mats = wb.create_sheet("Перечень материалов")
    _write_list_sheet(ws_mats, materials, list_headers_sub)

    # ── Sheet 5: Пояснительная записка (two sections) ──────────────────────
    ws_note = wb.create_sheet("Пояснительная записка")
    ws_note.column_dimensions["A"].width = 120

    FALLBACK = "Документация соответствует друг другу, дополнений не требуется"

    if not changes_summary:
        _write_note_section(ws_note, 1, "Пояснительная записка", FALLBACK)
    else:
        import re
        split_match = re.search(r"(?i)раздел\s*2", changes_summary)
        if split_match:
            part1 = changes_summary[: split_match.start()].strip()
            part2 = changes_summary[split_match.start():].strip()
        else:
            part1 = changes_summary.strip()
            part2 = ""

        current_row = _write_note_section(
            ws_note, 1,
            "Раздел 1 — Сравнение ТЗ и проекта",
            part1 or FALLBACK,
        )
        if part2:
            _write_note_section(
                ws_note, current_row + 1,
                "Раздел 2 — Изменения по нормативной базе",
                part2,
            )

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def generate_smeta(items: list) -> bytes:
    """
    Generate full smeta Excel.
    items: list of dicts with: type, name, unit, quantity,
           work_price (per unit), material_price (per unit), notes
    """
    wb = openpyxl.Workbook()
    VAT_RATE = 0.20

    # Sheet 1: Смета
    ws = wb.active
    ws.title = "Смета"

    headers = [
        "№",
        "Тип",
        "Наименование",
        "Ед. изм.",
        "Кол-во",
        "Цена работы (за ед.)",
        "Цена материала (за ед.)",
        "Стоимость работ",
        "Стоимость материалов",
        "Итого без НДС",
        "НДС (20%)",
        "Итого с НДС",
        "Наименование в прайсе",
        "Источники",
        "Примечание",
    ]
    for col, h in enumerate(headers, start=1):
        ws.cell(row=1, column=col, value=h)
    _style_header_row(ws, 1, len(headers))
    ws.row_dimensions[1].height = 40

    for i, item in enumerate(items, start=1):
        row = i + 1
        qty = item.get("quantity") or 0
        wp = item.get("work_price") or 0
        mp = item.get("material_price") or 0

        ws.cell(row=row, column=1, value=i)
        ws.cell(row=row, column=2, value=item.get("type", ""))
        ws.cell(row=row, column=3, value=item.get("name", ""))
        ws.cell(row=row, column=4, value=item.get("unit", ""))
        ws.cell(row=row, column=5, value=qty)
        ws.cell(row=row, column=6, value=wp if wp else None)
        ws.cell(row=row, column=7, value=mp if mp else None)

        work_total = qty * wp
        mat_total = qty * mp
        subtotal = work_total + mat_total
        vat = subtotal * VAT_RATE
        total = subtotal + vat

        ws.cell(row=row, column=8, value=work_total if work_total else None)
        ws.cell(row=row, column=9, value=mat_total if mat_total else None)
        ws.cell(row=row, column=10, value=subtotal if subtotal else None)
        ws.cell(row=row, column=11, value=vat if vat else None)
        ws.cell(row=row, column=12, value=total if total else None)
        ws.cell(row=row, column=13, value=item.get("price_list_name", "") or "")
        ws.cell(row=row, column=14, value=item.get("sources", "") or "")
        ws.cell(row=row, column=15, value=item.get("notes", ""))
        _style_data_row(ws, row, len(headers))

    # Totals row
    total_row = len(items) + 2
    ws.cell(row=total_row, column=1, value="ИТОГО")
    ws.merge_cells(
        start_row=total_row, start_column=1, end_row=total_row, end_column=7
    )
    data_start = 2
    data_end = len(items) + 1

    for col in [8, 9, 10, 11, 12]:
        col_letter = get_column_letter(col)
        ws.cell(
            row=total_row,
            column=col,
            value=f"=SUM({col_letter}{data_start}:{col_letter}{data_end})",
        )
        ws.cell(row=total_row, column=col).number_format = '#,##0.00'

    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=total_row, column=col)
        cell.fill = TOTAL_FILL
        cell.font = BOLD_FONT
        cell.border = THIN_BORDER

    # Number formats for currency columns
    for col in [6, 7, 8, 9, 10, 11, 12]:
        for row in range(2, len(items) + 2):
            ws.cell(row=row, column=col).number_format = '#,##0.00'

    _auto_fit_columns(ws)
    ws.freeze_panes = "A2"

    # Sheet 2: Работы
    works = [it for it in items if it.get("type", "").lower() in ("работа", "work", "работы")]
    ws_w = wb.create_sheet("Работы")
    w_headers = ["№", "Наименование", "Ед. изм.", "Кол-во", "Цена за ед.", "Стоимость", "Наименование в прайсе", "Источники"]
    for col, h in enumerate(w_headers, start=1):
        ws_w.cell(row=1, column=col, value=h)
    _style_header_row(ws_w, 1, len(w_headers))
    ws_w.row_dimensions[1].height = 30

    for i, item in enumerate(works, start=1):
        row = i + 1
        qty = item.get("quantity") or 0
        price = item.get("work_price") or 0
        ws_w.cell(row=row, column=1, value=i)
        ws_w.cell(row=row, column=2, value=item.get("name", ""))
        ws_w.cell(row=row, column=3, value=item.get("unit", ""))
        ws_w.cell(row=row, column=4, value=qty)
        ws_w.cell(row=row, column=5, value=price if price else None)
        ws_w.cell(row=row, column=6, value=qty * price if price else None)
        ws_w.cell(row=row, column=7, value=item.get("price_list_name", "") or "")
        ws_w.cell(row=row, column=8, value=item.get("sources", "") or "")
        _style_data_row(ws_w, row, len(w_headers))

    if works:
        sum_row = len(works) + 2
        ws_w.cell(row=sum_row, column=1, value="ИТОГО")
        ws_w.merge_cells(start_row=sum_row, start_column=1, end_row=sum_row, end_column=5)
        ws_w.cell(
            row=sum_row,
            column=6,
            value=f"=SUM(F2:F{len(works)+1})",
        )
        for col in range(1, len(w_headers) + 1):
            cell = ws_w.cell(row=sum_row, column=col)
            cell.fill = TOTAL_FILL
            cell.font = BOLD_FONT
            cell.border = THIN_BORDER

    _auto_fit_columns(ws_w)
    ws_w.freeze_panes = "A2"

    # Sheet 3: Материалы
    materials = [it for it in items if it.get("type", "").lower() in ("материал", "material", "материалы")]
    ws_m = wb.create_sheet("Материалы")
    m_headers = ["№", "Наименование", "Ед. изм.", "Кол-во", "Цена за ед.", "Стоимость", "Наименование в прайсе", "Источники"]
    for col, h in enumerate(m_headers, start=1):
        ws_m.cell(row=1, column=col, value=h)
    _style_header_row(ws_m, 1, len(m_headers))
    ws_m.row_dimensions[1].height = 30

    for i, item in enumerate(materials, start=1):
        row = i + 1
        qty = item.get("quantity") or 0
        price = item.get("material_price") or 0
        ws_m.cell(row=row, column=1, value=i)
        ws_m.cell(row=row, column=2, value=item.get("name", ""))
        ws_m.cell(row=row, column=3, value=item.get("unit", ""))
        ws_m.cell(row=row, column=4, value=qty)
        ws_m.cell(row=row, column=5, value=price if price else None)
        ws_m.cell(row=row, column=6, value=qty * price if price else None)
        ws_m.cell(row=row, column=7, value=item.get("price_list_name", "") or "")
        ws_m.cell(row=row, column=8, value=item.get("sources", "") or "")
        _style_data_row(ws_m, row, len(m_headers))

    if materials:
        sum_row = len(materials) + 2
        ws_m.cell(row=sum_row, column=1, value="ИТОГО")
        ws_m.merge_cells(start_row=sum_row, start_column=1, end_row=sum_row, end_column=5)
        ws_m.cell(
            row=sum_row,
            column=6,
            value=f"=SUM(F2:F{len(materials)+1})",
        )
        for col in range(1, len(m_headers) + 1):
            cell = ws_m.cell(row=sum_row, column=col)
            cell.fill = TOTAL_FILL
            cell.font = BOLD_FONT
            cell.border = THIN_BORDER

    _auto_fit_columns(ws_m)
    ws_m.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def generate_smeta_detailed(items: list) -> bytes:
    """
    Generate detailed smeta Excel with 3 sheets and VAT sub-columns.
    items: list of dicts with:
        type, name, unit, quantity,
        work_price (ex. VAT), mat_price (ex. VAT),
        usn (bool: if True, VAT=0), price_list_name, notes
    """
    VAT_RATE = 0.22
    wb = openpyxl.Workbook()

    def _vat_triple(price, usn: bool):
        """Return (ex_vat, vat, inc_vat) for a given price."""
        if not price:
            return None, None, None
        vat = 0.0 if usn else price * VAT_RATE
        return price, vat, price + vat

    def _write_sheet1(ws, rows):
        """Sheet 1: Перечень работ и материалов (all items)."""
        # Row 1: group headers with merges
        groups = [
            (1, 1, "№ п/п"),
            (2, 2, "Работа/\nМатериал"),
            (3, 3, "Наименование"),
            (4, 4, "Ед. изм."),
            (5, 5, "Кол-во"),
            (6, 8, "Цена за ед. изм.\nРаботы"),
            (9, 11, "Стоимость работ\nруб."),
            (12, 14, "Цена за ед. изм.\nМатериала"),
            (15, 17, "Стоимость\nМатериала руб."),
            (18, 18, "Наименование\nв прайсе"),
            (19, 19, "Примечание"),
        ]
        for c_start, c_end, title in groups:
            ws.cell(row=1, column=c_start, value=title)
            if c_start == c_end:
                ws.merge_cells(start_row=1, start_column=c_start, end_row=2, end_column=c_start)
            else:
                ws.merge_cells(start_row=1, start_column=c_start, end_row=1, end_column=c_end)
        # Row 2: sub-headers for VAT columns
        for col, label in [
            (6, "без НДС"), (7, "НДС"), (8, "с НДС"),
            (9, "без НДС"), (10, "НДС"), (11, "с НДС"),
            (12, "без НДС"), (13, "НДС"), (14, "с НДС"),
            (15, "без НДС"), (16, "НДС"), (17, "с НДС"),
        ]:
            ws.cell(row=2, column=col, value=label)
        total_cols = 19
        _style_header_row(ws, 1, total_cols)
        _style_header_row(ws, 2, total_cols)
        ws.row_dimensions[1].height = 40
        ws.row_dimensions[2].height = 30

        for i, item in enumerate(rows, start=1):
            r = i + 2
            qty = item.get("quantity") or 0
            wp = item.get("work_price") or 0
            mp = item.get("mat_price") or 0
            usn = item.get("usn", False)

            wp_ex, wp_vat, wp_inc = _vat_triple(wp, usn)
            mp_ex, mp_vat, mp_inc = _vat_triple(mp, usn)
            wt_ex = (wp_ex or 0) * qty or None
            wt_vat = (wp_vat or 0) * qty or None
            wt_inc = (wp_inc or 0) * qty or None
            mt_ex = (mp_ex or 0) * qty or None
            mt_vat = (mp_vat or 0) * qty or None
            mt_inc = (mp_inc or 0) * qty or None

            vals = [
                i, item.get("type", ""), item.get("name", ""),
                item.get("unit", ""), qty if qty else None,
                wp_ex, wp_vat, wp_inc,
                wt_ex, wt_vat, wt_inc,
                mp_ex, mp_vat, mp_inc,
                mt_ex, mt_vat, mt_inc,
                item.get("price_list_name", ""),
                item.get("notes", ""),
            ]
            for col, val in enumerate(vals, start=1):
                ws.cell(row=r, column=col, value=val)
            _style_data_row(ws, r, total_cols)

        # Currency format
        for col in range(6, 18):
            for r in range(3, len(rows) + 3):
                ws.cell(row=r, column=col).number_format = '#,##0.00'

        # Totals row
        if rows:
            tr = len(rows) + 3
            ws.cell(row=tr, column=1, value="ИТОГО")
            ws.merge_cells(start_row=tr, start_column=1, end_row=tr, end_column=5)
            data_start, data_end = 3, len(rows) + 2
            for col in range(9, 18):
                cl = get_column_letter(col)
                ws.cell(row=tr, column=col,
                        value=f"=SUM({cl}{data_start}:{cl}{data_end})")
                ws.cell(row=tr, column=col).number_format = '#,##0.00'
            for col in range(1, total_cols + 1):
                c = ws.cell(row=tr, column=col)
                c.fill = TOTAL_FILL
                c.font = BOLD_FONT
                c.border = THIN_BORDER

        _auto_fit_columns(ws)
        ws.freeze_panes = "A3"

    def _write_sheet_works(ws, works):
        """Sheet 2: Перечень работ."""
        total_cols = 12
        groups = [
            (1, 1, "№ п/п"),
            (2, 2, "Наименование"),
            (3, 3, "Ед. изм."),
            (4, 4, "Кол-во"),
            (5, 7, "Цена за ед. изм.\nРаботы"),
            (8, 10, "Стоимость работ\nруб."),
            (11, 11, "Наименование\nв прайсе"),
            (12, 12, "Примечание"),
        ]
        for c_start, c_end, title in groups:
            ws.cell(row=1, column=c_start, value=title)
            if c_start == c_end:
                ws.merge_cells(start_row=1, start_column=c_start, end_row=2, end_column=c_start)
            else:
                ws.merge_cells(start_row=1, start_column=c_start, end_row=1, end_column=c_end)
        for col, label in [(5, "без НДС"), (6, "НДС"), (7, "с НДС"),
                           (8, "без НДС"), (9, "НДС"), (10, "с НДС")]:
            ws.cell(row=2, column=col, value=label)
        _style_header_row(ws, 1, total_cols)
        _style_header_row(ws, 2, total_cols)
        ws.row_dimensions[1].height = 40
        ws.row_dimensions[2].height = 30

        for i, item in enumerate(works, start=1):
            r = i + 2
            qty = item.get("quantity") or 0
            wp = item.get("work_price") or 0
            usn = item.get("usn", False)
            wp_ex, wp_vat, wp_inc = _vat_triple(wp, usn)
            wt_ex = (wp_ex or 0) * qty or None
            wt_vat = (wp_vat or 0) * qty or None
            wt_inc = (wp_inc or 0) * qty or None
            vals = [
                i, item.get("name", ""), item.get("unit", ""),
                qty if qty else None,
                wp_ex, wp_vat, wp_inc,
                wt_ex, wt_vat, wt_inc,
                item.get("price_list_name", ""), item.get("notes", ""),
            ]
            for col, val in enumerate(vals, start=1):
                ws.cell(row=r, column=col, value=val)
            _style_data_row(ws, r, total_cols)

        for col in range(5, 11):
            for r in range(3, len(works) + 3):
                ws.cell(row=r, column=col).number_format = '#,##0.00'

        if works:
            tr = len(works) + 3
            ws.cell(row=tr, column=1, value="ИТОГО")
            ws.merge_cells(start_row=tr, start_column=1, end_row=tr, end_column=4)
            for col in range(8, 11):
                cl = get_column_letter(col)
                ws.cell(row=tr, column=col,
                        value=f"=SUM({cl}3:{cl}{len(works)+2})")
                ws.cell(row=tr, column=col).number_format = '#,##0.00'
            for col in range(1, total_cols + 1):
                c = ws.cell(row=tr, column=col)
                c.fill = TOTAL_FILL
                c.font = BOLD_FONT
                c.border = THIN_BORDER

        _auto_fit_columns(ws)
        ws.freeze_panes = "A3"

    def _write_sheet_materials(ws, materials):
        """Sheet 3: Перечень материалов."""
        total_cols = 12
        groups = [
            (1, 1, "№ п/п"),
            (2, 2, "Наименование"),
            (3, 3, "Ед. изм."),
            (4, 4, "Кол-во"),
            (5, 7, "Цена за ед. изм.\nМатериала"),
            (8, 10, "Стоимость\nМатериала руб."),
            (11, 11, "Наименование\nв прайсе"),
            (12, 12, "Примечание"),
        ]
        for c_start, c_end, title in groups:
            ws.cell(row=1, column=c_start, value=title)
            if c_start == c_end:
                ws.merge_cells(start_row=1, start_column=c_start, end_row=2, end_column=c_start)
            else:
                ws.merge_cells(start_row=1, start_column=c_start, end_row=1, end_column=c_end)
        for col, label in [(5, "без НДС"), (6, "НДС"), (7, "с НДС"),
                           (8, "без НДС"), (9, "НДС"), (10, "с НДС")]:
            ws.cell(row=2, column=col, value=label)
        _style_header_row(ws, 1, total_cols)
        _style_header_row(ws, 2, total_cols)
        ws.row_dimensions[1].height = 40
        ws.row_dimensions[2].height = 30

        for i, item in enumerate(materials, start=1):
            r = i + 2
            qty = item.get("quantity") or 0
            mp = item.get("mat_price") or 0
            usn = item.get("usn", False)
            mp_ex, mp_vat, mp_inc = _vat_triple(mp, usn)
            mt_ex = (mp_ex or 0) * qty or None
            mt_vat = (mp_vat or 0) * qty or None
            mt_inc = (mp_inc or 0) * qty or None
            vals = [
                i, item.get("name", ""), item.get("unit", ""),
                qty if qty else None,
                mp_ex, mp_vat, mp_inc,
                mt_ex, mt_vat, mt_inc,
                item.get("price_list_name", ""), item.get("notes", ""),
            ]
            for col, val in enumerate(vals, start=1):
                ws.cell(row=r, column=col, value=val)
            _style_data_row(ws, r, total_cols)

        for col in range(5, 11):
            for r in range(3, len(materials) + 3):
                ws.cell(row=r, column=col).number_format = '#,##0.00'

        if materials:
            tr = len(materials) + 3
            ws.cell(row=tr, column=1, value="ИТОГО")
            ws.merge_cells(start_row=tr, start_column=1, end_row=tr, end_column=4)
            for col in range(8, 11):
                cl = get_column_letter(col)
                ws.cell(row=tr, column=col,
                        value=f"=SUM({cl}3:{cl}{len(materials)+2})")
                ws.cell(row=tr, column=col).number_format = '#,##0.00'
            for col in range(1, total_cols + 1):
                c = ws.cell(row=tr, column=col)
                c.fill = TOTAL_FILL
                c.font = BOLD_FONT
                c.border = THIN_BORDER

        _auto_fit_columns(ws)
        ws.freeze_panes = "A3"

    ws1 = wb.active
    ws1.title = "Перечень работ и материалов"
    _write_sheet1(ws1, items)

    works = [it for it in items if it.get("type", "").lower() in ("работа", "work", "работы")]
    ws2 = wb.create_sheet("Перечень работ")
    _write_sheet_works(ws2, works)

    materials = [it for it in items if it.get("type", "").lower() in ("материал", "material", "материалы")]
    ws3 = wb.create_sheet("Перечень материалов")
    _write_sheet_materials(ws3, materials)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def generate_scan_result(data: dict) -> bytes:
    """
    Generate Excel from scan/OCR result.
    data: {
      header: {title, date, contractor, object},
      sections: [{title, items: [{name, unit, qty, price, total, notes}]}],
      summary: {total_works, total_materials, total_vat, grand_total}
    }
    """
    wb = openpyxl.Workbook()

    # Sheet 1: Информация
    ws_info = wb.active
    ws_info.title = "Информация"

    header = data.get("header", {})
    info_rows = [
        ("Документ", header.get("title", "")),
        ("Дата", header.get("date", "")),
        ("Подрядчик", header.get("contractor", "")),
        ("Объект", header.get("object", "")),
    ]

    for row_idx, (key, val) in enumerate(info_rows, start=1):
        ws_info.cell(row=row_idx, column=1, value=key).font = BOLD_FONT
        ws_info.cell(row=row_idx, column=2, value=val)

    _auto_fit_columns(ws_info)

    # Sheet 2: Данные
    ws_data = wb.create_sheet("Данные")
    headers = ["№", "Раздел", "Наименование", "Ед. изм.", "Кол-во", "Цена", "Сумма", "Примечание"]
    for col, h in enumerate(headers, start=1):
        ws_data.cell(row=1, column=col, value=h)
    _style_header_row(ws_data, 1, len(headers))
    ws_data.row_dimensions[1].height = 30

    row_idx = 2
    item_num = 0
    sections = data.get("sections", [])

    for section in sections:
        section_title = section.get("title", "")
        # Section header row
        ws_data.cell(row=row_idx, column=1, value="")
        ws_data.cell(row=row_idx, column=2, value=section_title)
        ws_data.merge_cells(
            start_row=row_idx, start_column=2, end_row=row_idx, end_column=len(headers)
        )
        for col in range(1, len(headers) + 1):
            cell = ws_data.cell(row=row_idx, column=col)
            cell.fill = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
            cell.font = BOLD_FONT
            cell.border = THIN_BORDER
        row_idx += 1

        for item in section.get("items", []):
            item_num += 1
            ws_data.cell(row=row_idx, column=1, value=item_num)
            ws_data.cell(row=row_idx, column=2, value=section_title)
            ws_data.cell(row=row_idx, column=3, value=item.get("name", ""))
            ws_data.cell(row=row_idx, column=4, value=item.get("unit", ""))
            ws_data.cell(row=row_idx, column=5, value=item.get("qty"))
            ws_data.cell(row=row_idx, column=6, value=item.get("price"))
            ws_data.cell(row=row_idx, column=7, value=item.get("total"))
            ws_data.cell(row=row_idx, column=8, value=item.get("notes", ""))
            _style_data_row(ws_data, row_idx, len(headers))
            row_idx += 1

    _auto_fit_columns(ws_data)
    ws_data.freeze_panes = "A2"

    # Sheet 3: Итоги
    ws_summary = wb.create_sheet("Итоги")
    summary = data.get("summary", {})
    summary_rows = [
        ("Итого работ", summary.get("total_works", "")),
        ("Итого материалов", summary.get("total_materials", "")),
        ("НДС (20%)", summary.get("total_vat", "")),
        ("Итого с НДС", summary.get("grand_total", "")),
    ]

    ws_summary.cell(row=1, column=1, value="Показатель").font = HEADER_FONT
    ws_summary.cell(row=1, column=1).fill = HEADER_FILL
    ws_summary.cell(row=1, column=2, value="Значение").font = HEADER_FONT
    ws_summary.cell(row=1, column=2).fill = HEADER_FILL

    for row_idx, (key, val) in enumerate(summary_rows, start=2):
        ws_summary.cell(row=row_idx, column=1, value=key).font = BOLD_FONT
        cell_val = ws_summary.cell(row=row_idx, column=2, value=val)
        if isinstance(val, (int, float)):
            cell_val.number_format = '#,##0.00'

    _auto_fit_columns(ws_summary)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
