import io
from datetime import datetime

import openpyxl
from openpyxl.styles import Font, PatternFill

from app.constants import TASK_TYPE_LABELS, ESTIMATION_STATUS_LABELS

_HEADER_FILL = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")
_TOTAL_FILL = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
_BOLD = Font(bold=True)


def generate_project_xlsx(project, tasks: list, slot_results: dict, base_url: str) -> bytes:
    # project is accepted for API consistency with pdf_exporter (name, description used there)
    """
    Generate xlsx bytes for a project export.

    Args:
        project: Project ORM instance (id, name, description)
        tasks: list of Task ORM instances
        slot_results: dict with keys 'source'/'estimate'/'optimized',
                      each value is list of (Task, TaskResult) tuples
        base_url: backend base URL for hyperlinks, e.g. "https://host.com"

    Returns: bytes of the xlsx file
    """
    wb = openpyxl.Workbook()

    # ── Sheet 1: Задачи ─────────────────────────────────────────────────
    ws = wb.active
    ws.title = "Задачи"

    headers = ["Тип задачи", "Статус сметы", "Стоимость (₽)", "Дата создания"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = _BOLD
        cell.fill = _HEADER_FILL

    ws.column_dimensions["A"].width = 35
    ws.column_dimensions["B"].width = 20
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 20

    total_cost = 0.0
    has_cost = False
    unestimated = estimated = optimized = 0

    for row_idx, task in enumerate(tasks, 2):
        type_label = TASK_TYPE_LABELS.get(task.task_type, task.task_type)
        status_label = ESTIMATION_STATUS_LABELS.get(task.estimation_status, task.estimation_status)
        cost = float(task.cost) if task.cost is not None else None
        if isinstance(task.created_at, datetime):
            created = task.created_at.strftime("%d.%m.%Y")
        else:
            created = str(task.created_at)

        ws.cell(row=row_idx, column=1, value=type_label)
        ws.cell(row=row_idx, column=2, value=status_label)
        cost_cell = ws.cell(row=row_idx, column=3, value=cost)
        cost_cell.number_format = "#,##0.00"
        ws.cell(row=row_idx, column=4, value=created)

        if cost is not None:
            total_cost += cost
            has_cost = True
        if task.estimation_status == "unestimated":
            unestimated += 1
        elif task.estimation_status == "estimated":
            estimated += 1
        elif task.estimation_status == "optimized":
            optimized += 1

    # Total row
    total_row = len(tasks) + 2
    summary = f"не рассчитано: {unestimated} / рассчитано: {estimated} / оптимизировано: {optimized}"
    for col in range(1, 5):
        ws.cell(row=total_row, column=col).font = _BOLD
        ws.cell(row=total_row, column=col).fill = _TOTAL_FILL
    ws.cell(row=total_row, column=1, value="ИТОГО")
    ws.cell(row=total_row, column=2, value=summary)
    total_cell = ws.cell(row=total_row, column=3, value=total_cost if has_cost else None)
    total_cell.number_format = "#,##0.00"

    # ── Sheets 2-4: Slots ───────────────────────────────────────────────
    slot_config = [
        ("source", "Исходные файлы"),
        ("estimate", "Расчёты"),
        ("optimized", "Оптимизированные"),
    ]
    for slot, sheet_name in slot_config:
        ws_s = wb.create_sheet(title=sheet_name)
        for col, h in enumerate(["Тип задачи", "Имя файла", "Ссылка"], 1):
            cell = ws_s.cell(row=1, column=col, value=h)
            cell.font = _BOLD
            cell.fill = _HEADER_FILL
        ws_s.column_dimensions["A"].width = 35
        ws_s.column_dimensions["B"].width = 30
        ws_s.column_dimensions["C"].width = 50

        pairs = slot_results.get(slot, [])
        if not pairs:
            ws_s.cell(row=2, column=1, value="Файлы отсутствуют")
        else:
            for row_idx, (task, task_result) in enumerate(pairs, 2):
                url = f"{base_url}/tasks/{task.id}/files/{slot}/download"
                ws_s.cell(row=row_idx, column=1, value=TASK_TYPE_LABELS.get(task.task_type, task.task_type))
                ws_s.cell(row=row_idx, column=2, value=task_result.file_name)
                link_cell = ws_s.cell(row=row_idx, column=3, value=f'=HYPERLINK("{url}")')

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def generate_estimate_xlsx(items: list[dict]) -> bytes:
    """
    Generate Excel estimate file for ESTIMATE_FROM_LIST task.

    Each item dict must have:
      type, name, unit, quantity,
      work_price, material_price,   (float | None)
      price_list_name,              (str | None — matched name from price list)
      sources,                      (str | None — Claude sources)
      notes                         (str | None)

    Appends totals block at the end.
    Returns raw xlsx bytes.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Смета"

    HEADER_FILL_EST = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    WORK_ROW_FILL = PatternFill(start_color="EBF3FB", end_color="EBF3FB", fill_type="solid")
    TOTAL_FILL_EST = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
    GRAND_TOTAL_FILL = PatternFill(start_color="70AD47", end_color="70AD47", fill_type="solid")

    headers = [
        "№",
        "Наименование",
        "Ед. изм.",
        "Кол-во",
        "Цена работ",
        "Стоимость работ",
        "Цена матер.",
        "Стоимость матер.",
        "Из прайса",
        "Источники",
        "Примечания",
    ]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL_EST

    # Column widths
    col_widths = [5, 50, 10, 10, 14, 18, 14, 18, 10, 45, 35]
    for i, w in enumerate(col_widths, 1):
        from openpyxl.utils import get_column_letter
        ws.column_dimensions[get_column_letter(i)].width = w

    total_works = 0.0
    total_materials = 0.0
    row_num = 2
    idx = 0
    for item in items:
        idx += 1
        qty = item.get("quantity") or 0
        work_price = item.get("work_price")
        mat_price = item.get("material_price")
        work_cost = round(qty * work_price, 2) if work_price is not None and qty else None
        mat_cost = round(qty * mat_price, 2) if mat_price is not None and qty else None

        if work_cost is not None:
            total_works += work_cost
        if mat_cost is not None:
            total_materials += mat_cost

        from_price_list = bool(item.get("price_list_name"))
        is_work = str(item.get("type", "")).strip() == "Работа"

        row_fill = WORK_ROW_FILL if is_work else None

        values = [
            idx,
            item.get("name", ""),
            item.get("unit", ""),
            item.get("quantity"),
            work_price,
            work_cost,
            mat_price,
            mat_cost,
            "Да" if from_price_list else "Нет",
            item.get("sources", "") or "",
            item.get("notes", "") or "",
        ]
        for col, val in enumerate(values, 1):
            cell = ws.cell(row=row_num, column=col, value=val)
            cell.font = Font(bold=is_work)
            if row_fill:
                cell.fill = row_fill
            if col in (5, 6, 7, 8) and isinstance(val, (int, float)):
                cell.number_format = "#,##0.00"
            if col == 4 and isinstance(val, (int, float)):
                cell.number_format = "#,##0.##"
        row_num += 1

    # Totals block
    overhead = round(total_works * 0.03, 2)
    transport = round(total_materials * 0.03, 2)
    grand_total = round(total_works + overhead + total_materials + transport, 2)

    totals = [
        ("Сумма по работам:", total_works),
        ("Накладные расходы 3%:", overhead),
        ("Сумма по материалам:", total_materials),
        ("Транспортные расходы 3%:", transport),
        ("ИТОГО ПО СМЕТЕ:", grand_total),
    ]

    row_num += 1  # blank separator
    for label, value in totals:
        is_grand = label.startswith("ИТОГО")
        fill = GRAND_TOTAL_FILL if is_grand else TOTAL_FILL_EST
        label_cell = ws.cell(row=row_num, column=1, value=label)
        label_cell.font = Font(bold=True)
        label_cell.fill = fill
        # Merge label across cols 1-9
        ws.merge_cells(start_row=row_num, start_column=1, end_row=row_num, end_column=9)
        val_cell = ws.cell(row=row_num, column=10, value=value)
        val_cell.font = Font(bold=True)
        val_cell.fill = fill
        val_cell.number_format = "#,##0.00"
        row_num += 1

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), grand_total
