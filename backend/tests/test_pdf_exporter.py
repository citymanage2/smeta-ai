from decimal import Decimal
from datetime import datetime, timezone

import pytest

from app.utils.pdf_exporter import generate_project_pdf, _build_html


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


def test_pdf_html_contains_project_name():
    project, tasks, slot_results = _make_data()
    html = _build_html(project, tasks, slot_results, "http://localhost:8000")
    assert "Тест проект" in html


def test_pdf_html_contains_task_type_label():
    project, tasks, slot_results = _make_data()
    html = _build_html(project, tasks, slot_results, "http://localhost:8000")
    assert "Смета из ТЗ" in html  # SMETA_FROM_LIST label


def test_pdf_html_contains_download_link():
    project, tasks, slot_results = _make_data()
    html = _build_html(project, tasks, slot_results, "http://localhost:8000")
    assert "http://localhost:8000/tasks/t1/files/estimate/download" in html


def test_pdf_html_empty_slot_shows_placeholder():
    project, tasks, slot_results = _make_data()
    html = _build_html(project, tasks, slot_results, "http://localhost:8000")
    assert "Файлы отсутствуют" in html


def test_pdf_html_contains_itogo_row():
    project, tasks, slot_results = _make_data()
    html = _build_html(project, tasks, slot_results, "http://localhost:8000")
    assert "ИТОГО" in html
