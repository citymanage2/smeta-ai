"""Result listing and download endpoint tests."""
import pytest


SEEDED_TASK_ID = "00000000-0000-0000-0000-000000000001"


async def test_list_results(async_client, seed_users, user_token):
    """GET /tasks/{task_id}/results returns list with seeded result file."""
    response = await async_client.get(
        f"/tasks/{SEEDED_TASK_ID}/results",
        headers={"Authorization": user_token},
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["file_name"] == "result.xlsx"


async def test_list_results_no_auth(async_client, seed_users):
    """GET /tasks/{task_id}/results without auth returns 401."""
    response = await async_client.get(f"/tasks/{SEEDED_TASK_ID}/results")
    assert response.status_code in (401, 403)


async def test_download_result(async_client, seed_users, user_token):
    """GET /results/{file_id}/download returns the file bytes."""
    # First discover the file_id from the list endpoint
    list_resp = await async_client.get(
        f"/tasks/{SEEDED_TASK_ID}/results",
        headers={"Authorization": user_token},
    )
    assert list_resp.status_code == 200
    file_id = list_resp.json()[0]["file_id"]

    response = await async_client.get(
        f"/results/{file_id}/download",
        headers={"Authorization": user_token},
    )
    assert response.status_code == 200
    assert response.content == b"fake-excel-content"
    content_disposition = response.headers.get("content-disposition", "")
    assert "result.xlsx" in content_disposition


async def test_download_result_not_found(async_client, seed_users, user_token):
    """GET /results/99999/download returns 404."""
    response = await async_client.get(
        "/results/99999/download",
        headers={"Authorization": user_token},
    )
    assert response.status_code == 404
