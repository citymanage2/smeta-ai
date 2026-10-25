from datetime import datetime, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.models.task import Task


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


def _task(project_id: str, estimation_status: str, cost=None, **over) -> Task:
    return Task(
        owner_id=1, user_role="user", task_type="ESTIMATE_FROM_LIST", status="completed",
        input_files=[], input_file_data=[], chat_history=[],
        project_id=project_id, estimation_status=estimation_status, cost=cost, **over,
    )


@pytest.mark.asyncio
async def test_list_projects(async_client: AsyncClient, user_token: str, db_session):
    """Карточка проекта в списке: счётчики смет по статусу и сумма посчитанных.

    В сумму идут только посчитанные и оптимизированные сметы; удалённая в
    корзину задача не считается нигде.
    """
    created = await async_client.post(
        "/projects",
        json={"name": "Проект А"},
        headers={"Authorization": user_token},
    )
    project_id = created.json()["id"]
    tasks = [
        _task(project_id, "unestimated"),
        _task(project_id, "estimated", cost=Decimal("1000.50")),
        _task(project_id, "optimized", cost=Decimal("2500.00")),
        _task(project_id, "not_applicable"),
        _task(project_id, "estimated", cost=Decimal("99999.00"),
              deleted_at=datetime.now(timezone.utc)),
    ]
    db_session.add_all(tasks)
    await db_session.commit()
    try:
        resp = await async_client.get(
            "/projects",
            headers={"Authorization": user_token},
        )

        assert resp.status_code == 200
        card = next(p for p in resp.json() if p["id"] == project_id)
        assert card["unestimated"] == 1
        assert card["estimated"] == 1
        assert card["optimized"] == 1
        assert card["other"] == 1
        assert card["total_cost"] == 3500.5
    finally:
        await db_session.execute(delete(Task).where(Task.project_id == project_id))
        await db_session.commit()


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
async def test_get_project_not_found(async_client: AsyncClient, user_token: str):
    resp = await async_client.get(
        "/projects/00000000-0000-0000-0000-000000000099",
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 404
