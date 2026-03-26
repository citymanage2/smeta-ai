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
