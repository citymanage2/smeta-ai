import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_project(async_client: AsyncClient, user_token: str):
    resp = await async_client.post(
        "/projects",
        json={"name": "Тестовый проект", "description": "Описание"},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Тестовый проект"
    assert data["description"] == "Описание"
    assert "id" in data


@pytest.mark.asyncio
async def test_list_projects(async_client: AsyncClient, user_token: str):
    await async_client.post(
        "/projects",
        json={"name": "Проект А"},
        headers={"Authorization": user_token},
    )
    resp = await async_client.get(
        "/projects",
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list)
    assert len(items) >= 1
    item = items[0]
    assert "id" in item
    assert "name" in item
    assert "unestimated" in item
    assert "estimated" in item
    assert "optimized" in item
    assert "other" in item
    assert "total_cost" in item


@pytest.mark.asyncio
async def test_get_project_detail(async_client: AsyncClient, user_token: str):
    create_resp = await async_client.post(
        "/projects",
        json={"name": "Детальный проект"},
        headers={"Authorization": user_token},
    )
    project_id = create_resp.json()["id"]

    resp = await async_client.get(
        f"/projects/{project_id}",
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == project_id
    assert "tasks" in data


@pytest.mark.asyncio
async def test_patch_project(async_client: AsyncClient, user_token: str):
    create_resp = await async_client.post(
        "/projects",
        json={"name": "Старое название"},
        headers={"Authorization": user_token},
    )
    project_id = create_resp.json()["id"]

    resp = await async_client.patch(
        f"/projects/{project_id}",
        json={"name": "Новое название"},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Новое название"


@pytest.mark.asyncio
async def test_delete_project_soft_deletes_for_any_user(
    async_client: AsyncClient, user_token: str
):
    """Мягкое удаление (в корзину) разрешено любому авторизованному пользователю.

    Начиная с редизайна «удаление в корзину» soft-delete обратим и доступен
    обычным пользователям; админ по-прежнему требуется только для необратимых
    операций (permanent-delete и очистка корзины).
    """
    create_resp = await async_client.post(
        "/projects",
        json={"name": "Удаляемый"},
        headers={"Authorization": user_token},
    )
    project_id = create_resp.json()["id"]

    resp = await async_client.delete(
        f"/projects/{project_id}",
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200

    # Проект перемещён в корзину — обычным detail-эндпоинтом больше не виден.
    get_resp = await async_client.get(
        f"/projects/{project_id}",
        headers={"Authorization": user_token},
    )
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_project_as_admin(async_client: AsyncClient, admin_token: str):
    create_resp = await async_client.post(
        "/projects",
        json={"name": "Удаляемый"},
        headers={"Authorization": admin_token},
    )
    project_id = create_resp.json()["id"]

    resp = await async_client.delete(
        f"/projects/{project_id}",
        headers={"Authorization": admin_token},
    )
    assert resp.status_code == 200

    get_resp = await async_client.get(
        f"/projects/{project_id}",
        headers={"Authorization": admin_token},
    )
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_get_project_not_found(async_client: AsyncClient, user_token: str):
    resp = await async_client.get(
        "/projects/00000000-0000-0000-0000-000000000099",
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 404
