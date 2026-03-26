"""Tests for GET /tasks/{task_id}/history and POST /tasks/{task_id}/history/{id}/revert."""
import io
import pytest
import pytest_asyncio
import openpyxl
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.models.task import Task
from app.models.result import TaskResult
from app.models.history import TaskHistory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_xlsx_bytes() -> bytes:
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


TASK_ID = "d1000000-0000-0000-0000-000000000001"
_TASK_ID_HEX = TASK_ID.replace("-", "")

ENTRY_ID_1 = "e1000000-0000-0000-0000-000000000001"
ENTRY_ID_2 = "e2000000-0000-0000-0000-000000000002"

_ENTRY_ID_1_HEX = ENTRY_ID_1.replace("-", "")
_ENTRY_ID_2_HEX = ENTRY_ID_2.replace("-", "")

_NOW = datetime(2026, 3, 26, 10, 0, 0, tzinfo=timezone.utc)
_LATER = _NOW + timedelta(hours=1)


@pytest_asyncio.fixture
async def seed_history_task(db_session: AsyncSession):
    """Seed a task with one history entry."""
    task = Task(
        id=TASK_ID,
        user_role="user",
        task_type="SMETA_FROM_LIST",
        status="completed",
        estimation_status="optimized",
        input_files=[],
        input_file_data=[],
        chat_history=[],
    )
    db_session.add(task)
    await db_session.flush()

    entry = TaskHistory(
        id=ENTRY_ID_1,
        task_id=TASK_ID,
        operation_type="optimization",
        slot="optimized",
        description="Оптимизация: найдено 1 из 1 аналогов",
        previous_value={"estimation_status": "estimated"},
        new_value={
            "file_name": "optimized.xlsx",
            "file_data_b64": "dGVzdA==",
            "estimation_status": "optimized",
        },
        created_at=_NOW,
    )
    db_session.add(entry)
    await db_session.commit()
    yield
    await db_session.execute(
        text("DELETE FROM task_history WHERE task_id = :tid"), {"tid": _TASK_ID_HEX}
    )
    await db_session.execute(
        text("DELETE FROM tasks WHERE id = :tid"), {"tid": _TASK_ID_HEX}
    )
    await db_session.commit()


# ---------------------------------------------------------------------------
# Tests: GET /history
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_history_returns_entries(
    async_client: AsyncClient, user_token: str, seed_history_task
):
    """GET /history returns 200 with list of entries."""
    resp = await async_client.get(
        f"/tasks/{TASK_ID}/history",
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["operation_type"] == "optimization"
    assert data[0]["description"] == "Оптимизация: найдено 1 из 1 аналогов"
    assert "id" in data[0]
    assert "created_at" in data[0]
    # file_data_b64 must NOT be in the response
    assert "file_data_b64" not in data[0]
    assert "previous_value" not in data[0]


@pytest.mark.asyncio
async def test_get_history_task_not_found(async_client: AsyncClient, user_token: str):
    """GET /history returns 404 for nonexistent task."""
    resp = await async_client.get(
        "/tasks/nonexistent-id/history",
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 404
