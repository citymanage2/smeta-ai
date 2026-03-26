"""Admin panel endpoint tests."""
import uuid
import pytest
from sqlalchemy import text


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
    assert data["task_type"] == "LIST_FROM_TZ"
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
        data={"task_type": "LIST_FROM_TZ"},
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


# ---------------------------------------------------------------------------
# Tests for GET /admin/fix-db
# ---------------------------------------------------------------------------

async def test_fix_db_requires_admin(async_client, seed_users, user_token):
    """GET /admin/fix-db with user (non-admin) token must return 403."""
    resp = await async_client.get(
        "/admin/fix-db",
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 403


async def test_fix_db_requires_auth(async_client, seed_users):
    """GET /admin/fix-db without auth must return 401."""
    resp = await async_client.get("/admin/fix-db")
    assert resp.status_code == 401


async def test_fix_db_response_structure(async_client, seed_users, admin_token):
    """
    GET /admin/fix-db must return HTTP 200 with all 6 expected steps in the
    response JSON. Each step entry must have 'step' and 'status' keys.

    This test only validates the response contract — not step success, because
    the SQL is PostgreSQL-specific and will fail in the SQLite test DB.
    Step success is validated by test_schema_integrity.py against real PostgreSQL.
    """
    resp = await async_client.get(
        "/admin/fix-db",
        headers={"Authorization": admin_token},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert "success" in data
    assert "steps" in data
    assert "message" in data
    assert isinstance(data["steps"], list)

    by_name = {s["step"]: s for s in data["steps"]}

    for expected in (
        "create_projects_table",
        "add_tasks_project_id",
        "add_tasks_estimation_status",
        "add_tasks_cost",
        "add_task_results_slot",
        "update_alembic_version",
    ):
        assert expected in by_name, f"Step '{expected}' missing from response"
        step = by_name[expected]
        assert "status" in step, f"Step '{expected}' has no 'status' key"
        assert step["status"] in ("ok", "error"), (
            f"Step '{expected}' has unexpected status: {step['status']!r}"
        )


async def test_fix_db_schema_is_correct_after_run(
    async_client, db_session, seed_users, admin_token
):
    """
    After calling fix-db, the projects table and required columns must exist
    in the test database.

    This is the key regression test: it FAILS if fix-db does not actually
    create the missing schema objects.
    """
    resp = await async_client.get(
        "/admin/fix-db",
        headers={"Authorization": admin_token},
    )
    assert resp.status_code == 200

    # Check projects table exists (SQLite: sqlite_master)
    result = await db_session.execute(
        text(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='projects'"
        )
    )
    count = result.scalar()
    assert count == 1, "projects table does not exist after fix-db"

    # Check tasks.project_id column exists (SQLite: PRAGMA table_info)
    result = await db_session.execute(text("PRAGMA table_info(tasks)"))
    task_cols = {row[1] for row in result.fetchall()}
    assert "project_id" in task_cols, (
        f"tasks.project_id missing after fix-db. Columns: {task_cols}"
    )
    assert "estimation_status" in task_cols, (
        f"tasks.estimation_status missing after fix-db. Columns: {task_cols}"
    )
    assert "cost" in task_cols, (
        f"tasks.cost missing after fix-db. Columns: {task_cols}"
    )

    # Check task_results.slot column
    result = await db_session.execute(text("PRAGMA table_info(task_results)"))
    result_cols = {row[1] for row in result.fetchall()}
    assert "slot" in result_cols, (
        f"task_results.slot missing after fix-db. Columns: {result_cols}"
    )
