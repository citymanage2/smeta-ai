"""Task creation and status polling tests."""
import pytest


SEEDED_TASK_ID = "00000000-0000-0000-0000-000000000001"


async def test_create_task(async_client, seed_users, user_token):
    """Authenticated POST /tasks creates a task and returns task_id + status=pending."""
    response = await async_client.post(
        "/tasks",
        data={"task_type": "LIST_FROM_TZ"},
        files={"files": ("test.pdf", b"%PDF-1.4 test", "application/pdf")},
        headers={"Authorization": user_token},
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data.get("task_id"), str)
    assert len(data["task_id"]) > 0
    assert data["status"] == "pending"


async def test_create_task_no_auth(async_client, seed_users):
    """POST /tasks without auth header returns 401."""
    response = await async_client.post(
        "/tasks",
        data={"task_type": "LIST_FROM_TZ"},
        files={"files": ("test.pdf", b"%PDF-1.4 test", "application/pdf")},
    )
    assert response.status_code in (401, 403)


async def test_get_task_status(async_client, seed_users, user_token):
    """GET /tasks/{task_id}/status for seeded task returns completed status."""
    response = await async_client.get(
        f"/tasks/{SEEDED_TASK_ID}/status",
        headers={"Authorization": user_token},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["task_type"] == "LIST_FROM_TZ"


async def test_get_task_status_not_found(async_client, seed_users, user_token):
    """GET /tasks/{unknown_id}/status returns 404."""
    response = await async_client.get(
        "/tasks/00000000-0000-0000-0000-999999999999/status",
        headers={"Authorization": user_token},
    )
    assert response.status_code == 404
