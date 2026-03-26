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
