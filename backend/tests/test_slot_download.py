import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_slot_download_returns_file(async_client: AsyncClient, user_token: str, db_session):
    """Source slot download serves from task.input_file_data (not TaskResult)."""
    import uuid
    import base64
    from app.models.task import Task

    task_id = str(uuid.uuid4())
    file_content = b"fake-xlsx-bytes"
    task = Task(
        id=task_id,
        user_role="user",
        task_type="LIST_FROM_GRAND",
        status="completed",
        input_files=[{"name": "source.xlsx", "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "size_bytes": len(file_content)}],
        input_file_data=[{
            "name": "source.xlsx",
            "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "size_bytes": len(file_content),
            "content_b64": base64.b64encode(file_content).decode(),
        }],
        chat_history=[],
        estimation_status="not_applicable",
    )
    db_session.add(task)
    await db_session.commit()

    resp = await async_client.get(
        f"/tasks/{task_id}/files/source/download",
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    assert resp.content == file_content
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
        task_type="LIST_FROM_GRAND",
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
        task_type="LIST_FROM_GRAND",
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
