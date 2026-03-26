import io
import pytest
import openpyxl
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.task import Task
from app.models.result import TaskResult


SEEDED_TASK_ID = "a1000000-0000-0000-0000-000000000001"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _make_xlsx_with_итого(cost: float) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Работа", "Сумма"])
    ws.append(["Итого", cost])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_xlsx_no_итого() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Работа", "Сумма"])
    ws.append(["Нет итого", 500])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_upload_source_slot(
    async_client: AsyncClient,
    user_token: str,
    seed_users,
    db_session: AsyncSession,
):
    result = await db_session.execute(select(Task).where(Task.id == SEEDED_TASK_ID))
    task = result.scalar_one()
    task.task_type = "SMETA_FROM_LIST"
    task.estimation_status = "unestimated"
    await db_session.commit()

    xlsx_bytes = _make_xlsx_no_итого()
    resp = await async_client.post(
        f"/tasks/{SEEDED_TASK_ID}/files",
        headers={"Authorization": user_token},
        files={"file": ("source.xlsx", xlsx_bytes, XLSX_MIME)},
        data={"slot": "source"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["slot"] == "source"

    res = await db_session.execute(
        select(TaskResult)
        .where(TaskResult.task_id == SEEDED_TASK_ID, TaskResult.slot == "source")
    )
    row = res.scalar_one_or_none()
    assert row is not None
    assert row.file_name == "source.xlsx"


@pytest.mark.asyncio
async def test_upload_estimate_slot_parses_cost(
    async_client: AsyncClient,
    user_token: str,
    seed_users,
    db_session: AsyncSession,
):
    result = await db_session.execute(select(Task).where(Task.id == SEEDED_TASK_ID))
    task = result.scalar_one()
    task.task_type = "SMETA_FROM_LIST"
    task.estimation_status = "unestimated"
    task.cost = None
    await db_session.commit()

    xlsx_bytes = _make_xlsx_with_итого(150000.50)
    resp = await async_client.post(
        f"/tasks/{SEEDED_TASK_ID}/files",
        headers={"Authorization": user_token},
        files={"file": ("estimate.xlsx", xlsx_bytes, XLSX_MIME)},
        data={"slot": "estimate"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["estimation_status"] == "estimated"
    assert data["cost"] == pytest.approx(150000.50, abs=0.01)


@pytest.mark.asyncio
async def test_upload_estimate_slot_damaged_xlsx_returns_warning(
    async_client: AsyncClient,
    user_token: str,
    seed_users,
    db_session: AsyncSession,
):
    result = await db_session.execute(select(Task).where(Task.id == SEEDED_TASK_ID))
    task = result.scalar_one()
    task.task_type = "SMETA_FROM_LIST"
    task.estimation_status = "unestimated"
    await db_session.commit()

    resp = await async_client.post(
        f"/tasks/{SEEDED_TASK_ID}/files",
        headers={"Authorization": user_token},
        files={"file": ("bad.xlsx", b"not really xlsx", XLSX_MIME)},
        data={"slot": "estimate"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["estimation_status"] == "unestimated"
    assert data["cost"] is None
    assert "warning" in data


@pytest.mark.asyncio
async def test_upload_non_xlsx_to_estimate_returns_400(
    async_client: AsyncClient,
    user_token: str,
    seed_users,
    db_session: AsyncSession,
):
    result = await db_session.execute(select(Task).where(Task.id == SEEDED_TASK_ID))
    task = result.scalar_one()
    task.task_type = "SMETA_FROM_LIST"
    task.estimation_status = "unestimated"
    await db_session.commit()

    resp = await async_client.post(
        f"/tasks/{SEEDED_TASK_ID}/files",
        headers={"Authorization": user_token},
        files={"file": ("doc.pdf", b"%PDF-fake", "application/pdf")},
        data={"slot": "estimate"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_estimate_slot_clears_cost(
    async_client: AsyncClient,
    user_token: str,
    seed_users,
    db_session: AsyncSession,
):
    result = await db_session.execute(select(Task).where(Task.id == SEEDED_TASK_ID))
    task = result.scalar_one()
    task.task_type = "SMETA_FROM_LIST"
    task.estimation_status = "estimated"
    task.cost = 99000
    await db_session.commit()

    slot_result = TaskResult(
        task_id=SEEDED_TASK_ID,
        file_name="estimate.xlsx",
        mime_type=XLSX_MIME,
        file_data=b"fake",
        slot="estimate",
    )
    db_session.add(slot_result)
    await db_session.commit()

    resp = await async_client.delete(
        f"/tasks/{SEEDED_TASK_ID}/files/estimate",
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200

    await db_session.refresh(task)
    assert task.cost is None
    assert task.estimation_status == "unestimated"


@pytest.mark.asyncio
async def test_confirm_optimized_estimation(
    async_client: AsyncClient,
    user_token: str,
    seed_users,
    db_session: AsyncSession,
):
    result = await db_session.execute(select(Task).where(Task.id == SEEDED_TASK_ID))
    task = result.scalar_one()
    task.task_type = "SMETA_FROM_LIST"
    task.estimation_status = "estimated"
    await db_session.commit()

    slot_result = TaskResult(
        task_id=SEEDED_TASK_ID,
        file_name="optimized.xlsx",
        mime_type=XLSX_MIME,
        file_data=b"fake",
        slot="optimized",
    )
    db_session.add(slot_result)
    await db_session.commit()

    resp = await async_client.patch(
        f"/tasks/{SEEDED_TASK_ID}/estimation",
        json={"estimation_status": "optimized"},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    assert resp.json()["estimation_status"] == "optimized"


@pytest.mark.asyncio
async def test_confirm_optimized_fails_without_file(
    async_client: AsyncClient,
    user_token: str,
    seed_users,
    db_session: AsyncSession,
):
    result = await db_session.execute(select(Task).where(Task.id == SEEDED_TASK_ID))
    task = result.scalar_one()
    task.task_type = "SMETA_FROM_LIST"
    task.estimation_status = "estimated"
    await db_session.commit()

    resp = await async_client.patch(
        f"/tasks/{SEEDED_TASK_ID}/estimation",
        json={"estimation_status": "optimized"},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_patch_task_project(
    async_client: AsyncClient,
    user_token: str,
    seed_users,
    db_session: AsyncSession,
):
    proj_resp = await async_client.post(
        "/projects",
        json={"name": "Тест проект"},
        headers={"Authorization": user_token},
    )
    project_id = proj_resp.json()["id"]

    resp = await async_client.patch(
        f"/tasks/{SEEDED_TASK_ID}/project",
        json={"project_id": project_id},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    assert resp.json()["project_id"] == project_id


@pytest.mark.asyncio
async def test_detach_task_from_project(
    async_client: AsyncClient,
    user_token: str,
    seed_users,
    db_session: AsyncSession,
):
    resp = await async_client.patch(
        f"/tasks/{SEEDED_TASK_ID}/project",
        json={"project_id": None},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    assert resp.json()["project_id"] is None
