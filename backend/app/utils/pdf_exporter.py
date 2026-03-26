from datetime import datetime
from html import escape

from weasyprint import HTML

from app.constants import TASK_TYPE_LABELS, ESTIMATION_STATUS_LABELS


def generate_project_pdf(project, tasks: list, slot_results: dict, base_url: str) -> bytes:
    """
    Generate PDF bytes for a project export.

    Args:
        project: Project ORM instance (id, name, description)
        tasks: list of Task ORM instances
        slot_results: dict with keys 'source'/'estimate'/'optimized',
                      each value is list of (Task, TaskResult) tuples
        base_url: backend base URL for hyperlinks, e.g. "https://host.com"

    Returns: bytes of the PDF file
    """
    html = _build_html(project, tasks, slot_results, base_url)
    return HTML(string=html).write_pdf()


def _build_html(project, tasks: list, slot_results: dict, base_url: str) -> str:
    task_rows = ""
    total_cost = 0.0
    has_cost = False

    for task in tasks:
        type_label = TASK_TYPE_LABELS.get(task.task_type, task.task_type)
        status_label = ESTIMATION_STATUS_LABELS.get(task.estimation_status, task.estimation_status)
        if task.cost is not None:
            cost_str = f"{float(task.cost):,.2f} ₽".replace(",", " ")
            total_cost += float(task.cost)
            has_cost = True
        else:
            cost_str = "—"
        if isinstance(task.created_at, datetime):
            created = task.created_at.strftime("%d.%m.%Y %H:%M")
        else:
            created = str(task.created_at)
        task_rows += (
            f"<tr>"
            f"<td>{escape(type_label)}</td>"
            f"<td>{escape(status_label)}</td>"
            f"<td>{cost_str}</td>"
            f"<td>{created}</td>"
            f"</tr>\n"
        )

    total_str = f"{total_cost:,.2f} ₽".replace(",", " ") if has_cost else "—"

    slot_config = [
        ("source", "Исходные файлы"),
        ("estimate", "Расчёты"),
        ("optimized", "Оптимизированные"),
    ]
    slot_sections = ""
    for slot, title in slot_config:
        pairs = slot_results.get(slot, [])
        slot_sections += f"<h2>{title}</h2>"
        if pairs:
            items = "".join(
                f'<li><a href="{base_url}/tasks/{task.id}/files/{slot}/download">'
                f"{escape(tr.file_name)}</a></li>"
                for task, tr in pairs
            )
            slot_sections += f"<ul>{items}</ul>"
        else:
            slot_sections += "<p>Файлы отсутствуют</p>"

    export_date = datetime.now().strftime("%d.%m.%Y")
    description_html = f"<p>{escape(project.description)}</p>" if project.description else ""

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: Arial, sans-serif; font-size: 12px; margin: 20mm; color: #1e293b; }}
  h1 {{ font-size: 20px; margin-bottom: 4px; }}
  h2 {{ font-size: 14px; margin-top: 24px; margin-bottom: 8px; color: #374151; }}
  .meta {{ color: #64748b; font-size: 11px; margin-bottom: 16px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
  th {{ background: #D9D9D9; font-weight: bold; padding: 6px 8px;
        border: 1px solid #aaa; text-align: left; }}
  td {{ padding: 6px 8px; border: 1px solid #e2e8f0; }}
  tr:nth-child(even) td {{ background: #f8fafc; }}
  .total-row td {{ background: #BDD7EE !important; font-weight: bold; }}
  a {{ color: #2563eb; }}
  ul {{ margin: 6px 0; padding-left: 20px; line-height: 1.9; }}
</style>
</head>
<body>
<h1>{escape(project.name)}</h1>
{description_html}
<p class="meta">Дата экспорта: {export_date}</p>
<table>
<thead>
  <tr>
    <th>Тип задачи</th>
    <th>Статус сметы</th>
    <th>Стоимость (₽)</th>
    <th>Дата создания</th>
  </tr>
</thead>
<tbody>
{task_rows}
<tr class="total-row">
  <td>ИТОГО</td><td></td><td>{total_str}</td><td></td>
</tr>
</tbody>
</table>
{slot_sections}
</body>
</html>"""
