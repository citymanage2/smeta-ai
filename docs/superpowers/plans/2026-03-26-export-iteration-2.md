# Export Iteration 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add xlsx and PDF export for projects, plus a slot-file download endpoint.

**Architecture:** Two pure-Python generator utilities (xlsx_exporter, pdf_exporter) called from a new `GET /projects/{id}/export?format=xlsx|pdf` endpoint. A new `GET /tasks/{id}/files/{slot}/download` endpoint streams stored slot files. Frontend adds `exportProject()` API function and export buttons to ProjectDetail and Projects pages.

**Tech Stack:** FastAPI + openpyxl + weasyprint / React + TypeScript + axios (blob responseType)

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/app/constants.py` | Modify | Add TASK_TYPE_LABELS, ESTIMATION_STATUS_LABELS |
| `backend/app/utils/xlsx_exporter.py` | Create | Generate project xlsx with openpyxl |
| `backend/app/utils/pdf_exporter.py` | Create | Generate project PDF via weasyprint |
| `backend/app/routers/tasks.py` | Modify | Add `GET /{task_id}/files/{slot}/download` |
| `backend/app/routers/projects.py` | Modify | Add `GET /{project_id}/export?format=xlsx\|pdf` |
| `backend/tests/test_export.py` | Create | Integration tests for export + download endpoints |
| `frontend/src/api/projects.ts` | Modify | Add `exportProject(projectId, format)` |
| `frontend/src/pages/ProjectDetail.tsx` | Modify | Add xlsx/PDF export buttons |
| `frontend/src/pages/Projects.tsx` | Modify | Add xlsx/PDF export buttons to cards |

---

### Task 1: Add TASK_TYPE_LABELS and ESTIMATION_STATUS_LABELS to constants.py

**Files:**
- Modify: `backend/app/constants.py`

- [ ] **Step 1: Update constants.py**

Replace the full contents of `backend/app/constants.py` with:

```python
ESTIMATE_TASK_TYPES = {
    "SMETA_FROM_LIST",
    "SMETA_FROM_PROJECT",
    "SMETA_FROM_EDC_PROJECT",
    "SMETA_FROM_GRAND_PROJECT",
    "SCAN_TO_EXCEL",
}

TASK_TYPE_LABELS: dict[str, str] = {
    "SMETA_FROM_LIST": "Смета из ТЗ",
    "SMETA_FROM_PROJECT": "Смета из проекта",
    "SMETA_FROM_EDC_PROJECT": "Смета из EDC-проекта",
    "SMETA_FROM_GRAND_PROJECT": "Смета из GRAND-проекта",
    "SCAN_TO_EXCEL": "Сканирование в Excel",
    "LIST_FROM_TZ": "Список из ТЗ",
    "LIST_FROM_TZ_PROJECT": "Список из ТЗ проекта",
    "LIST_FROM_PROJECT": "Список из проекта",
    "RESEARCH_PROJECT": "Исследование проекта",
    "COMPARE_PROJECT_SMETA": "Сравнение сметы",
}

ESTIMATION_STATUS_LABELS: dict[str, str] = {
    "unestimated": "Не рассчитано",
    "estimated": "Рассчитано",
    "optimized": "Оптимизировано",
    "not_applicable": "—",
}
```

- [ ] **Step 2: Verify existing tests still pass**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend
python3 -m pytest tests/test_xlsx_cost_parser.py -v
```

Expected: all 9 PASS (test_estimate_task_types_constant still works because ESTIMATE_TASK_TYPES is unchanged).

- [ ] **Step 3: Commit**

```bash
git add backend/app/constants.py
git commit -m "feat: add TASK_TYPE_LABELS and ESTIMATION_STATUS_LABELS to constants"
```

---

### Task 2: xlsx_exporter utility

**Files:**
- Create: `backend/app/utils/xlsx_exporter.py`
- Create: `backend/tests/test_xlsx_exporter.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_xlsx_exporter.py`:

```python
import io
from decimal import Decimal
from datetime import datetime, timezone

import openpyxl
import pytest

from app.utils.xlsx_exporter import generate_project_xlsx


class _FakeProject:
    id = "proj-1"
    name = "Тест проект"
    description = "Описание"


class _FakeTask:
    def __init__(self, tid, task_type, estimation_status, cost, created_at):
        self.id = tid
        self.task_type = task_type
        self.estimation_status = estimation_status
        self.cost = cost
        self.created_at = created_at


class _FakeResult:
    def __init__(self, task_id, file_name, slot):
        self.task_id = task_id
        self.file_name = file_name
        self.slot = slot


_DT = datetime(2026, 3, 26, 12, 0, 0, tzinfo=timezone.utc)


def _make_data():
    project = _FakeProject()
    tasks = [
        _FakeTask("t1", "SMETA_FROM_LIST", "estimated", Decimal("1500000"), _DT),
        _FakeTask("t2", "LIST_FROM_TZ", "not_applicable", None, _DT),
    ]
    result1 = _FakeResult("t1", "smeta.xlsx", "estimate")
    slot_results = {
        "source": [],
        "estimate": [(tasks[0], result1)],
        "optimized": [],
    }
    return project, tasks, slot_results


def test_xlsx_returns_bytes():
    project, tasks, slot_results = _make_data()
    data = generate_project_xlsx(project, tasks, slot_results, "http://localhost:8000")
    assert isinstance(data, bytes)
    assert len(data) > 0


def test_xlsx_has_tasks_sheet():
    project, tasks, slot_results = _make_data()
    data = generate_project_xlsx(project, tasks, slot_results, "http://localhost:8000")
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert "Задачи" in wb.sheetnames


def test_xlsx_tasks_sheet_headers():
    project, tasks, slot_results = _make_data()
    data = generate_project_xlsx(project, tasks, slot_results, "http://localhost:8000")
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb["Задачи"]
    assert ws.cell(1, 1).value == "Тип задачи"
    assert ws.cell(1, 2).value == "Статус сметы"
    assert ws.cell(1, 3).value == "Стоимость (₽)"
    assert ws.cell(1, 4).value == "Дата создания"


def test_xlsx_tasks_sheet_rows():
    project, tasks, slot_results = _make_data()
    data = generate_project_xlsx(project, tasks, slot_results, "http://localhost:8000")
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb["Задачи"]
    # Row 2 = first task
    assert ws.cell(2, 1).value == "Смета из ТЗ"
    assert ws.cell(2, 2).value == "Рассчитано"
    assert ws.cell(2, 3).value == 1500000.0
    # Row 3 = second task
    assert ws.cell(3, 1).value == "Список из ТЗ"
    assert ws.cell(3, 2).value == "—"
    assert ws.cell(3, 3).value is None


def test_xlsx_total_row_is_bold():
    project, tasks, slot_results = _make_data()
    data = generate_project_xlsx(project, tasks, slot_results, "http://localhost:8000")
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb["Задачи"]
    total_row = len(tasks) + 2
    assert ws.cell(total_row, 1).font.bold is True
    assert ws.cell(total_row, 1).value == "ИТОГО"


def test_xlsx_has_all_slot_sheets():
    project, tasks, slot_results = _make_data()
    data = generate_project_xlsx(project, tasks, slot_results, "http://localhost:8000")
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert "Исходные файлы" in wb.sheetnames
    assert "Расчёты" in wb.sheetnames
    assert "Оптимизированные" in wb.sheetnames


def test_xlsx_slot_sheet_with_file_has_hyperlink():
    project, tasks, slot_results = _make_data()
    data = generate_project_xlsx(project, tasks, slot_results, "http://localhost:8000")
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb["Расчёты"]
    # Row 2 has the estimate file
    assert ws.cell(2, 2).value == "smeta.xlsx"
    assert ws.cell(2, 3).hyperlink is not None


def test_xlsx_empty_slot_shows_placeholder():
    project, tasks, slot_results = _make_data()
    data = generate_project_xlsx(project, tasks, slot_results, "http://localhost:8000")
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb["Исходные файлы"]
    assert ws.cell(2, 1).value == "Файлы отсутствуют"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend
python3 -m pytest tests/test_xlsx_exporter.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.utils.xlsx_exporter'`

- [ ] **Step 3: Create xlsx_exporter.py**

Create `backend/app/utils/xlsx_exporter.py`:

```python
import io
from datetime import datetime

import openpyxl
from openpyxl.styles import Font, PatternFill

from app.constants import TASK_TYPE_LABELS, ESTIMATION_STATUS_LABELS

_HEADER_FILL = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")
_TOTAL_FILL = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
_BOLD = Font(bold=True)
_BOLD_HEADER = Font(bold=True)


def generate_project_xlsx(project, tasks: list, slot_results: dict, base_url: str) -> bytes:
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
        cell.font = _BOLD_HEADER
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
            created = task.created_at.strftime("%d.%m.%Y %H:%M")
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
            cell.font = _BOLD_HEADER
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
                link_cell = ws_s.cell(row=row_idx, column=3, value=task_result.file_name)
                link_cell.hyperlink = url
                link_cell.style = "Hyperlink"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend
python3 -m pytest tests/test_xlsx_exporter.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/utils/xlsx_exporter.py backend/tests/test_xlsx_exporter.py
git commit -m "feat: xlsx project exporter utility"
```

---

### Task 3: pdf_exporter utility

**Files:**
- Create: `backend/app/utils/pdf_exporter.py`
- Create: `backend/tests/test_pdf_exporter.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_pdf_exporter.py`:

```python
from decimal import Decimal
from datetime import datetime, timezone

import pytest

from app.utils.pdf_exporter import generate_project_pdf


class _FakeProject:
    id = "proj-1"
    name = "Тест проект"
    description = "Описание"


class _FakeTask:
    def __init__(self, tid, task_type, estimation_status, cost, created_at):
        self.id = tid
        self.task_type = task_type
        self.estimation_status = estimation_status
        self.cost = cost
        self.created_at = created_at


class _FakeResult:
    def __init__(self, task_id, file_name, slot):
        self.task_id = task_id
        self.file_name = file_name
        self.slot = slot


_DT = datetime(2026, 3, 26, 12, 0, 0, tzinfo=timezone.utc)


def _make_data():
    project = _FakeProject()
    tasks = [
        _FakeTask("t1", "SMETA_FROM_LIST", "estimated", Decimal("1500000"), _DT),
        _FakeTask("t2", "LIST_FROM_TZ", "not_applicable", None, _DT),
    ]
    result1 = _FakeResult("t1", "smeta.xlsx", "estimate")
    slot_results = {
        "source": [],
        "estimate": [(tasks[0], result1)],
        "optimized": [],
    }
    return project, tasks, slot_results


def test_pdf_returns_bytes():
    project, tasks, slot_results = _make_data()
    data = generate_project_pdf(project, tasks, slot_results, "http://localhost:8000")
    assert isinstance(data, bytes)
    assert len(data) > 0


def test_pdf_starts_with_pdf_magic():
    project, tasks, slot_results = _make_data()
    data = generate_project_pdf(project, tasks, slot_results, "http://localhost:8000")
    assert data[:4] == b"%PDF"


def test_pdf_no_description():
    """Project without description should not raise."""
    project = _FakeProject()
    project.description = None
    tasks = [_FakeTask("t1", "SMETA_FROM_LIST", "unestimated", None, _DT)]
    data = generate_project_pdf(project, tasks, {"source": [], "estimate": [], "optimized": []}, "http://localhost:8000")
    assert len(data) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend
python3 -m pytest tests/test_pdf_exporter.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.utils.pdf_exporter'`

- [ ] **Step 3: Create pdf_exporter.py**

Create `backend/app/utils/pdf_exporter.py`:

```python
from datetime import datetime

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
            f"<td>{type_label}</td>"
            f"<td>{status_label}</td>"
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
                f"{tr.file_name}</a></li>"
                for task, tr in pairs
            )
            slot_sections += f"<ul>{items}</ul>"
        else:
            slot_sections += "<p>Файлы отсутствуют</p>"

    export_date = datetime.now().strftime("%d.%m.%Y")
    description_html = f"<p>{project.description}</p>" if project.description else ""

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
<h1>{project.name}</h1>
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend
python3 -m pytest tests/test_pdf_exporter.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/utils/pdf_exporter.py backend/tests/test_pdf_exporter.py
git commit -m "feat: PDF project exporter utility via weasyprint"
```

---

### Task 4: Slot file download endpoint

**Files:**
- Modify: `backend/app/routers/tasks.py` (add endpoint at end of file)
- Create: `backend/tests/test_slot_download.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_slot_download.py`:

```python
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_slot_download_returns_file(async_client: AsyncClient, user_token: str, db_session):
    """Upload a file to source slot, then download it."""
    import uuid
    from app.models.task import Task
    from app.models.result import TaskResult

    task_id = str(uuid.uuid4())
    task = Task(
        id=task_id,
        user_role="user",
        task_type="LIST_FROM_TZ",
        status="completed",
        input_files=[],
        input_file_data=[],
        chat_history=[],
        estimation_status="not_applicable",
    )
    db_session.add(task)
    await db_session.flush()

    task_result = TaskResult(
        task_id=task_id,
        file_name="source.xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        file_data=b"fake-xlsx-bytes",
        slot="source",
    )
    db_session.add(task_result)
    await db_session.commit()

    resp = await async_client.get(
        f"/tasks/{task_id}/files/source/download",
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    assert resp.content == b"fake-xlsx-bytes"
    assert "attachment" in resp.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_slot_download_empty_slot_returns_404(async_client: AsyncClient, user_token: str, db_session):
    """Downloading from empty slot returns 404."""
    import uuid
    from app.models.task import Task

    task_id = str(uuid.uuid4())
    task = Task(
        id=task_id,
        user_role="user",
        task_type="LIST_FROM_TZ",
        status="completed",
        input_files=[],
        input_file_data=[],
        chat_history=[],
        estimation_status="not_applicable",
    )
    db_session.add(task)
    await db_session.commit()

    resp = await async_client.get(
        f"/tasks/{task_id}/files/estimate/download",
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_slot_download_invalid_slot_returns_400(async_client: AsyncClient, user_token: str, db_session):
    """Invalid slot name returns 400."""
    import uuid
    from app.models.task import Task

    task_id = str(uuid.uuid4())
    task = Task(
        id=task_id,
        user_role="user",
        task_type="LIST_FROM_TZ",
        status="completed",
        input_files=[],
        input_file_data=[],
        chat_history=[],
        estimation_status="not_applicable",
    )
    db_session.add(task)
    await db_session.commit()

    resp = await async_client.get(
        f"/tasks/{task_id}/files/invalid/download",
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_slot_download_task_not_found(async_client: AsyncClient, user_token: str):
    """Non-existent task returns 404."""
    resp = await async_client.get(
        "/tasks/b1000000-0000-0000-0000-000000000099/files/source/download",
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend
python3 -m pytest tests/test_slot_download.py -v
```

Expected: 4 FAILED with `404 Not Found` or route not found errors.

- [ ] **Step 3: Add download endpoint to tasks.py**

In `backend/app/routers/tasks.py`, add these two imports at the top of the file (alongside existing imports):

```python
import io
```

Also add to the FastAPI imports line (the existing `from fastapi import ...` block):
```
StreamingResponse
```
becomes part of the imports:
```python
from fastapi.responses import StreamingResponse
```

Then add the endpoint at the end of `backend/app/routers/tasks.py` (after the last existing endpoint):

```python
@router.get("/{task_id}/files/{slot}/download")
async def download_file_from_slot(
    task_id: str,
    slot: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if slot not in VALID_SLOTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Недопустимый слот. Допустимые значения: {', '.join(VALID_SLOTS)}",
        )

    task_row = await db.execute(select(Task).where(Task.id == task_id))
    task = task_row.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")

    result_row = await db.execute(
        select(TaskResult).where(
            TaskResult.task_id == task_id,
            TaskResult.slot == slot,
        )
    )
    task_result = result_row.scalar_one_or_none()
    if not task_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Файл в указанном слоте не найден",
        )

    return StreamingResponse(
        io.BytesIO(task_result.file_data),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{task_result.file_name}"',
        },
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend
python3 -m pytest tests/test_slot_download.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Run full test suite to check no regressions**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend
python3 -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all previous tests PASS + 4 new tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/tasks.py backend/tests/test_slot_download.py
git commit -m "feat: slot file download endpoint GET /tasks/{id}/files/{slot}/download"
```

---

### Task 5: Project export endpoint

**Files:**
- Modify: `backend/app/routers/projects.py`
- Create: `backend/tests/test_export.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_export.py`:

```python
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_export_xlsx_returns_file(async_client: AsyncClient, user_token: str):
    """Creating a project and exporting it as xlsx returns valid bytes."""
    create_resp = await async_client.post(
        "/projects",
        json={"name": "Экспорт проект", "description": "Тест"},
        headers={"Authorization": user_token},
    )
    assert create_resp.status_code == 200
    project_id = create_resp.json()["id"]

    resp = await async_client.get(
        f"/projects/{project_id}/export",
        params={"format": "xlsx"},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert len(resp.content) > 0
    assert "attachment" in resp.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_export_pdf_returns_file(async_client: AsyncClient, user_token: str):
    """Creating a project and exporting it as pdf returns valid bytes."""
    create_resp = await async_client.post(
        "/projects",
        json={"name": "PDF проект"},
        headers={"Authorization": user_token},
    )
    project_id = create_resp.json()["id"]

    resp = await async_client.get(
        f"/projects/{project_id}/export",
        params={"format": "pdf"},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")
    assert len(resp.content) > 0


@pytest.mark.asyncio
async def test_export_invalid_format_returns_400(async_client: AsyncClient, user_token: str):
    create_resp = await async_client.post(
        "/projects",
        json={"name": "Проект формат"},
        headers={"Authorization": user_token},
    )
    project_id = create_resp.json()["id"]

    resp = await async_client.get(
        f"/projects/{project_id}/export",
        params={"format": "docx"},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_export_project_not_found(async_client: AsyncClient, user_token: str):
    resp = await async_client.get(
        "/projects/c1000000-0000-0000-0000-000000000099/export",
        params={"format": "xlsx"},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_export_xlsx_is_valid_workbook(async_client: AsyncClient, user_token: str):
    """Exported xlsx can be opened with openpyxl."""
    import io
    import openpyxl

    create_resp = await async_client.post(
        "/projects",
        json={"name": "Валидный xlsx"},
        headers={"Authorization": user_token},
    )
    project_id = create_resp.json()["id"]

    resp = await async_client.get(
        f"/projects/{project_id}/export",
        params={"format": "xlsx"},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert "Задачи" in wb.sheetnames
    assert "Исходные файлы" in wb.sheetnames
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend
python3 -m pytest tests/test_export.py -v
```

Expected: 5 FAILED with `404 Not Found` (route not registered).

- [ ] **Step 3: Add export endpoint to projects.py**

At the top of `backend/app/routers/projects.py`, add these imports to the existing import block:

Add to the `from fastapi import ...` line: `Request`
Add new imports:

```python
import io
from fastapi.responses import StreamingResponse
```

Then add the export endpoint at the end of `backend/app/routers/projects.py` (after `delete_project`):

```python
@router.get("/{project_id}/export")
async def export_project(
    project_id: str,
    format: str = "xlsx",
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if format not in ("xlsx", "pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Параметр format должен быть xlsx или pdf",
        )

    project = await _get_project_or_404(project_id, db)

    tasks_result = await db.execute(
        select(Task).where(Task.project_id == project_id).order_by(Task.created_at.asc())
    )
    tasks = list(tasks_result.scalars().all())

    # Fetch TaskResults for all file slots in one query
    from app.models.result import TaskResult

    slot_results: dict[str, list] = {"source": [], "estimate": [], "optimized": []}
    if tasks:
        task_ids = [t.id for t in tasks]
        results_stmt = await db.execute(
            select(TaskResult).where(
                TaskResult.task_id.in_(task_ids),
                TaskResult.slot.in_(["source", "estimate", "optimized"]),
            )
        )
        task_results = list(results_stmt.scalars().all())
        task_map = {t.id: t for t in tasks}
        for tr in task_results:
            if tr.task_id in task_map:
                slot_results[tr.slot].append((task_map[tr.task_id], tr))

    base_url = str(request.base_url).rstrip("/") if request else ""

    if format == "xlsx":
        from app.utils.xlsx_exporter import generate_project_xlsx
        file_bytes = generate_project_xlsx(project, tasks, slot_results, base_url)
        safe_name = project.name.replace('"', '').replace('/', '-')
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"{safe_name}.xlsx"
    else:
        from app.utils.pdf_exporter import generate_project_pdf
        file_bytes = generate_project_pdf(project, tasks, slot_results, base_url)
        safe_name = project.name.replace('"', '').replace('/', '-')
        media_type = "application/pdf"
        filename = f"{safe_name}.pdf"

    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend
python3 -m pytest tests/test_export.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Run full test suite**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend
python3 -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/projects.py backend/tests/test_export.py
git commit -m "feat: project export endpoint GET /projects/{id}/export?format=xlsx|pdf"
```

---

### Task 6: Frontend — exportProject + export buttons

**Files:**
- Modify: `frontend/src/api/projects.ts`
- Modify: `frontend/src/pages/ProjectDetail.tsx`
- Modify: `frontend/src/pages/Projects.tsx`

- [ ] **Step 1: Add exportProject to api/projects.ts**

In `frontend/src/api/projects.ts`, add this function at the end of the file:

```typescript
export async function exportProject(projectId: string, format: 'xlsx' | 'pdf'): Promise<void> {
  const response = await apiClient.get(`/projects/${projectId}/export`, {
    params: { format },
    responseType: 'blob',
  });
  const contentDisposition: string = response.headers['content-disposition'] ?? '';
  const match = contentDisposition.match(/filename="?([^"]+)"?/);
  const ext = format === 'xlsx' ? 'xlsx' : 'pdf';
  const fileName = match ? match[1] : `project.${ext}`;
  const url = URL.createObjectURL(response.data as Blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  a.click();
  URL.revokeObjectURL(url);
}
```

- [ ] **Step 2: Add export buttons to ProjectDetail.tsx**

In `frontend/src/pages/ProjectDetail.tsx`, add the `exportProject` import to the existing import from `../api/projects`:

Change:
```tsx
import { getProject, updateProject, deleteProject } from '../api/projects';
```

To:
```tsx
import { getProject, updateProject, deleteProject, exportProject } from '../api/projects';
```

Add state variable inside `ProjectDetailPage` (alongside other `useState` declarations):

```tsx
  const [exporting, setExporting] = useState<'xlsx' | 'pdf' | null>(null);
```

Add handler function inside `ProjectDetailPage` (after `handleDelete`):

```tsx
  async function handleExport(format: 'xlsx' | 'pdf') {
    if (!projectId) return;
    setExporting(format);
    try {
      await exportProject(projectId, format);
    } catch {
      setError('Ошибка при экспорте проекта');
    } finally {
      setExporting(null);
    }
  }
```

Find the buttons row (the `<div style={{ display: 'flex', gap: '8px' }}>` containing «Изменить» and «Удалить»). Replace it with:

```tsx
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <button
                    onClick={() => handleExport('xlsx')}
                    disabled={exporting !== null}
                    style={{ padding: '7px 14px', backgroundColor: 'transparent', border: '1px solid #e2e8f0', borderRadius: '8px', cursor: exporting !== null ? 'not-allowed' : 'pointer', fontSize: '13px', color: '#15803d', fontWeight: 500 }}
                  >
                    {exporting === 'xlsx' ? '...' : '↓ xlsx'}
                  </button>
                  <button
                    onClick={() => handleExport('pdf')}
                    disabled={exporting !== null}
                    style={{ padding: '7px 14px', backgroundColor: 'transparent', border: '1px solid #e2e8f0', borderRadius: '8px', cursor: exporting !== null ? 'not-allowed' : 'pointer', fontSize: '13px', color: '#dc2626', fontWeight: 500 }}
                  >
                    {exporting === 'pdf' ? '...' : '↓ PDF'}
                  </button>
                  <button onClick={() => setEditing(true)} style={{ padding: '7px 14px', backgroundColor: 'transparent', border: '1px solid #e2e8f0', borderRadius: '8px', cursor: 'pointer', fontSize: '13px', color: '#64748b' }}>
                    Изменить
                  </button>
                  {isAdmin && (
                    <button onClick={handleDelete} style={{ padding: '7px 14px', backgroundColor: '#fee2e2', border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '13px', color: '#dc2626', fontWeight: 500 }}>
                      Удалить
                    </button>
                  )}
                </div>
```

- [ ] **Step 3: Add export buttons to Projects.tsx**

In `frontend/src/pages/Projects.tsx`, add `exportProject` import to the existing import from `../api/projects`:

Change:
```tsx
import { listProjects, createProject } from '../api/projects';
```

To:
```tsx
import { listProjects, createProject, exportProject } from '../api/projects';
```

Add state inside the `Projects` component (alongside existing state):

```tsx
  const [exportingCard, setExportingCard] = useState<{ id: string; format: 'xlsx' | 'pdf' } | null>(null);
```

Add handler inside the `Projects` component:

```tsx
  async function handleCardExport(projectId: string, format: 'xlsx' | 'pdf', e: React.MouseEvent) {
    e.stopPropagation();
    setExportingCard({ id: projectId, format });
    try {
      await exportProject(projectId, format);
    } catch {
      setError('Ошибка при экспорте проекта');
    } finally {
      setExportingCard(null);
    }
  }
```

Inside the project card `<div>` (after the badges `<div>` that ends with `{p.unestimated === 0 && ...}`), add the export row:

```tsx
                <div
                  style={{ display: 'flex', gap: '8px', marginTop: '12px', borderTop: '1px solid #f1f5f9', paddingTop: '12px' }}
                  onClick={(e) => e.stopPropagation()}
                >
                  <button
                    onClick={(e) => handleCardExport(p.id, 'xlsx', e)}
                    disabled={exportingCard !== null}
                    style={{ padding: '5px 12px', backgroundColor: 'transparent', border: '1px solid #e2e8f0', borderRadius: '6px', cursor: exportingCard !== null ? 'not-allowed' : 'pointer', fontSize: '12px', color: '#15803d', fontWeight: 500 }}
                  >
                    {exportingCard?.id === p.id && exportingCard?.format === 'xlsx' ? '...' : '↓ xlsx'}
                  </button>
                  <button
                    onClick={(e) => handleCardExport(p.id, 'pdf', e)}
                    disabled={exportingCard !== null}
                    style={{ padding: '5px 12px', backgroundColor: 'transparent', border: '1px solid #e2e8f0', borderRadius: '6px', cursor: exportingCard !== null ? 'not-allowed' : 'pointer', fontSize: '12px', color: '#dc2626', fontWeight: 500 }}
                  >
                    {exportingCard?.id === p.id && exportingCard?.format === 'pdf' ? '...' : '↓ PDF'}
                  </button>
                </div>
```

- [ ] **Step 4: Build frontend to verify no TypeScript errors**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/frontend
npm run build 2>&1 | tail -15
```

Expected: `✓ built in ...ms` — no TypeScript errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/projects.ts frontend/src/pages/ProjectDetail.tsx frontend/src/pages/Projects.tsx
git commit -m "feat: export buttons (xlsx/PDF) in ProjectDetail and Projects cards"
```

- [ ] **Step 6: Push to main**

```bash
git push origin main
```

---

## Self-Review

**Spec coverage:**
- ✅ `GET /projects/{id}/export?format=xlsx|pdf` — Task 5
- ✅ `GET /tasks/{id}/files/{slot}/download` — Task 4
- ✅ xlsx with 4 sheets (Задачи + 3 slots) — Task 2
- ✅ PDF with tasks table + slot sections + hyperlinks — Task 3
- ✅ Hyperlinks in xlsx point to download endpoint — Task 2
- ✅ Hyperlinks in PDF point to download endpoint — Task 3
- ✅ TASK_TYPE_LABELS, ESTIMATION_STATUS_LABELS — Task 1
- ✅ Export buttons on ProjectDetail — Task 6
- ✅ Export buttons on Projects cards — Task 6
- ✅ stopPropagation on card export buttons — Task 6
- ✅ Loading state during export — Task 6
- ✅ Error handling → setError — Task 6
- ✅ base_url from request.base_url — Task 5

**No placeholders:** All steps have complete code.

**Type consistency:**
- `generate_project_xlsx(project, tasks, slot_results, base_url)` — used consistently in Tasks 2, 5
- `generate_project_pdf(project, tasks, slot_results, base_url)` — used consistently in Tasks 3, 5
- `exportProject(projectId, format)` — used consistently in Tasks 6
- `exportingCard: { id: string; format: 'xlsx' | 'pdf' } | null` — used consistently in Projects.tsx
