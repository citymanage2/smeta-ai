"""Admin panel endpoint tests."""
import uuid
import pytest


SEEDED_TASK_ID = "a1000000-0000-0000-0000-000000000001"


async def test_admin_list_tasks(async_client, seed_users, admin_token):
    """GET /admin/tasks with admin token returns paginated task list."""
    response = await async_client.get(
        "/admin/tasks",
        headers={"Authorization": admin_token},
    )
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)
    assert data["total"] >= 1
    first = data["items"][0]
    assert "id" in first
    assert "task_type" in first
    assert "status" in first
    assert "created_at" in first


async def test_admin_list_tasks_requires_admin(async_client, seed_users, user_token):
    """GET /admin/tasks with user (non-admin) token returns 403."""
    response = await async_client.get(
        "/admin/tasks",
        headers={"Authorization": user_token},
    )
    assert response.status_code == 403
    assert "Недостаточно прав" in response.json()["detail"]


async def test_admin_list_tasks_no_auth(async_client, seed_users):
    """GET /admin/tasks without auth returns 401."""
    response = await async_client.get("/admin/tasks")
    assert response.status_code in (401, 403)


async def test_admin_get_task_detail(async_client, seed_users, admin_token):
    """GET /admin/tasks/{task_id} with admin token returns task detail."""
    response = await async_client.get(
        f"/admin/tasks/{SEEDED_TASK_ID}",
        headers={"Authorization": admin_token},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["task_type"] == "LIST_FROM_GRAND"
    assert isinstance(data["input_files"], list)
    assert isinstance(data["chat_history"], list)


async def test_admin_get_task_not_found(async_client, seed_users, admin_token):
    """GET /admin/tasks/{unknown_id} returns 404."""
    response = await async_client.get(
        "/admin/tasks/00000000-0000-0000-0000-999999999999",
        headers={"Authorization": admin_token},
    )
    assert response.status_code == 404


async def test_admin_download_input_file(async_client, seed_users, admin_token):
    """GET /admin/tasks/{task_id}/download-input/0 returns the original file."""
    response = await async_client.get(
        f"/admin/tasks/{SEEDED_TASK_ID}/download-input/0",
        headers={"Authorization": admin_token},
    )
    assert response.status_code == 200
    # content_b64 "dGVzdA==" decodes to b"test"
    assert response.content == b"test"
    content_disposition = response.headers.get("content-disposition", "")
    assert "test.pdf" in content_disposition


async def test_admin_download_input_file_bad_index(async_client, seed_users, admin_token):
    """GET /admin/tasks/{task_id}/download-input/99 returns 404."""
    response = await async_client.get(
        f"/admin/tasks/{SEEDED_TASK_ID}/download-input/99",
        headers={"Authorization": admin_token},
    )
    assert response.status_code == 404


async def test_admin_delete_task(async_client, seed_users, admin_token):
    """DELETE /admin/tasks/{task_id} removes the task and subsequent GET returns 404."""
    # Create a new task via the API first
    create_resp = await async_client.post(
        "/tasks",
        data={"task_type": "LIST_FROM_GRAND"},
        files={"files": ("del.pdf", b"%PDF-1.4 delete-me", "application/pdf")},
        headers={"Authorization": f"Bearer {_get_user_token()}"},
    )
    assert create_resp.status_code == 200
    new_task_id = create_resp.json()["task_id"]

    # Delete it
    del_resp = await async_client.delete(
        f"/admin/tasks/{new_task_id}",
        headers={"Authorization": admin_token},
    )
    assert del_resp.status_code == 204

    # Confirm it's gone
    get_resp = await async_client.get(
        f"/admin/tasks/{new_task_id}",
        headers={"Authorization": admin_token},
    )
    assert get_resp.status_code == 404


def _get_user_token() -> str:
    """Helper to generate a user token without fixture injection."""
    from app.utils.auth import create_access_token
    return create_access_token("user")
