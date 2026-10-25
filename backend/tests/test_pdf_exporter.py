import re
from decimal import Decimal
from datetime import datetime, timezone

from app.utils.pdf_exporter import _build_html


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
        _FakeTask("t1", "LIST_FROM_GRAND", "estimated", Decimal("1500000"), _DT),
        _FakeTask("t2", "LIST_FROM_GRAND", "not_applicable", None, _DT),
    ]
    result1 = _FakeResult("t1", "smeta.xlsx", "estimate")
    slot_results = {
        "source": [],
        "estimate": [(tasks[0], result1)],
        "optimized": [],
    }
    return project, tasks, slot_results


def test_pdf_html_contains_download_link():
    project, tasks, slot_results = _make_data()
    html = _build_html(project, tasks, slot_results, "http://localhost:8000")
    assert "http://localhost:8000/tasks/t1/files/estimate/download" in html


def _total_row_sum(html: str) -> float:
    """Число в строке ИТОГО таблицы задач (разделители разрядов — пробелы)."""
    (row,) = [r for r in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S) if "ИТОГО" in r]
    (amount,) = re.findall(r"([\d ]+\.\d{2}) ₽", row)
    return float(amount.replace(" ", ""))


def test_pdf_html_total_row_sums_task_costs():
    """ИТОГО — сумма стоимостей задач; задача без стоимости в сумму не входит."""
    project, _, slot_results = _make_data()
    tasks = [
        _FakeTask("t1", "LIST_FROM_GRAND", "estimated", Decimal("1000000"), _DT),
        _FakeTask("t2", "LIST_FROM_GRAND", "estimated", Decimal("500000"), _DT),
        _FakeTask("t3", "LIST_FROM_GRAND", "not_applicable", None, _DT),
    ]
    html = _build_html(project, tasks, slot_results, "http://localhost:8000")
    assert _total_row_sum(html) == 1_500_000
