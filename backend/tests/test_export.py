import io
import re
from datetime import datetime, timezone
from decimal import Decimal

import openpyxl
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete

from app.constants import TASK_TYPE_LABELS
from app.models.project import Project
from app.models.result import TaskResult
from app.models.task import Task
from tests.conftest import store_result_row

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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


@pytest_asyncio.fixture
async def project_with_tasks(async_client: AsyncClient, user_token: str, db_session):
    """Проект с тремя задачами: две посчитаны (у каждой свой файл), одна — нет.

    Задачи и файлы кладутся в БД напрямую: экспорт читает их оттуда, а как
    они туда попали (обработка, загрузка), ему всё равно.
    """
    resp = await async_client.post(
        "/projects", json={"name": "Объект экспорта"},
        headers={"Authorization": user_token},
    )
    project_id = resp.json()["id"]

    def _task(task_type, estimation_status, cost, day):
        return Task(
            owner_id=1, user_role="user", task_type=task_type, status="completed",
            input_files=[], input_file_data=[], chat_history=[],
            project_id=project_id, estimation_status=estimation_status, cost=cost,
            created_at=datetime(2026, 10, day, 12, 0, tzinfo=timezone.utc),
        )

    tasks = {
        "list": _task("LIST_FROM_GRAND", "not_applicable", None, 1),
        "estimate": _task("ESTIMATE_FROM_LIST", "estimated", Decimal("1500000.00"), 2),
        "optimized": _task("ESTIMATE_OPTIMIZATION", "optimized", Decimal("250000.50"), 3),
    }
    db_session.add_all(tasks.values())
    await db_session.flush()
    ids = {key: str(task.id) for key, task in tasks.items()}
    await store_result_row(db_session, ids["estimate"], "estimate", "Смета.xlsx", XLSX, b"smeta-bytes")
    await store_result_row(db_session, ids["optimized"], "optimized", "Оптимизация.xlsx", XLSX, b"opt-bytes")
    await db_session.commit()

    yield {"project": project_id, **ids}

    await db_session.rollback()
    await db_session.execute(delete(TaskResult).where(TaskResult.task_id.in_(ids.values())))
    await db_session.execute(delete(Task).where(Task.id.in_(ids.values())))
    await db_session.execute(delete(Project).where(Project.id == project_id))
    await db_session.commit()


async def test_export_xlsx_lists_tasks_costs_and_working_links(
    async_client: AsyncClient, user_token: str, project_with_tasks,
):
    """Экспорт проекта: задачи со стоимостью, итог и ссылки, по которым качается файл."""
    env = project_with_tasks
    resp = await async_client.get(
        f"/projects/{env['project']}/export",
        params={"format": "xlsx"},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))

    tasks = [row for row in wb["Задачи"].iter_rows(min_row=2, values_only=True)]
    # Задачи — по дате создания; у непосчитанной стоимости нет.
    assert [(row[0], row[2]) for row in tasks[:3]] == [
        (TASK_TYPE_LABELS["LIST_FROM_GRAND"], None),
        (TASK_TYPE_LABELS["ESTIMATE_FROM_LIST"], 1500000.0),
        (TASK_TYPE_LABELS["ESTIMATE_OPTIMIZATION"], 250000.5),
    ]
    total = tasks[3]
    assert total[2] == 1750000.5
    # Счётчики итога: не рассчитано / рассчитано / оптимизировано.
    assert [int(n) for n in re.findall(r"\d+", total[1])] == [0, 1, 1]

    # По ссылке из файла скачивается тот самый файл задачи.
    for sheet, task_key, content in (
        ("Расчёты", "estimate", b"smeta-bytes"),
        ("Оптимизированные", "optimized", b"opt-bytes"),
    ):
        (row,) = list(wb[sheet].iter_rows(min_row=2, values_only=True))
        url = re.fullmatch(r'=HYPERLINK\("(.+)"\)', row[2]).group(1)
        assert env[task_key] in url
        download = await async_client.get(
            url.removeprefix("http://test"), headers={"Authorization": user_token},
        )
        assert download.status_code == 200, sheet
        assert download.content == content
