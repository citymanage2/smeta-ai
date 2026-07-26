import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_slot_download_returns_file(async_client: AsyncClient, user_token: str, db_session):
    """Source slot download serves the first input file (bytes from S3)."""
    import uuid
    from app.models.task import Task
    from app.models.task_input_file import TaskInputFile
    from app.services import storage_service

    task_id = str(uuid.uuid4())
    file_content = b"fake-xlsx-bytes"
    _mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    task = Task(owner_id=1, 
        id=task_id,
        user_role="user",
        task_type="LIST_FROM_GRAND",
        status="completed",
        input_files=[{"name": "source.xlsx", "mime_type": _mime, "size_bytes": len(file_content)}],
        input_file_data=[{"name": "source.xlsx", "mime_type": _mime, "size_bytes": len(file_content)}],
        chat_history=[],
        estimation_status="not_applicable",
    )
    db_session.add(task)
    await db_session.flush()

    key = storage_service.build_input_key(task_id, 0, "source.xlsx")
    await storage_service.put_object(key, file_content, _mime)
    db_session.add(TaskInputFile(
        task_id=task_id,
        file_index=0,
        file_name="source.xlsx",
        mime_type=_mime,
        size_bytes=len(file_content),
        storage_key=key,
    ))
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
    task = Task(owner_id=1, 
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
    task = Task(owner_id=1, 
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
