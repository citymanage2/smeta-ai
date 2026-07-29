"""
Права на корпоративный каталог расценок.

Найдено ревью 2026-07-30: `PUT`/`DELETE`/`POST` расценок были защищены только
`get_current_user`, то есть любой авторизованный пользователь мог удалить или
переписать расценку. Загрузка того же прайса файлом
(`/admin/price-lists/works`) при этом требует администратора, а таблица одна и
та же — `PriceWork`/`PriceMaterial`, по ней считаются все сметы всех
пользователей.

Решение: изменяющие операции приведены к правам руководителя (`admin |
head_of_sales`). Рядовой project_manager каталог больше не меняет, но читать
может — сметы у него считаются как раньше.

План: plans/2026-07-30-ispravlenie-nahodok-code-review.md, Фаза 2.
"""
import pytest
from app.utils.auth import create_access_token

pytestmark = pytest.mark.asyncio


@pytest.fixture
def pm_token() -> str:
    """Рядовой исполнитель — та роль, которой каталог менять нельзя."""
    return f"Bearer {create_access_token(42, 'project_manager')}"


@pytest.fixture
def head_token() -> str:
    return f"Bearer {create_access_token(7, 'head_of_sales')}"


# ---------------------------------------------------------------------------
# Изменяющие операции закрыты для рядового пользователя
# ---------------------------------------------------------------------------

async def test_pm_cannot_delete_work(async_client, pm_token):
    r = await async_client.delete(
        "/prices/catalog/works/1", headers={"Authorization": pm_token}
    )
    assert r.status_code == 403


async def test_pm_cannot_delete_material(async_client, pm_token):
    r = await async_client.delete(
        "/prices/catalog/materials/1", headers={"Authorization": pm_token}
    )
    assert r.status_code == 403


async def test_pm_cannot_update_work(async_client, pm_token):
    r = await async_client.put(
        "/prices/catalog/works/1",
        json={"name": "Взлом", "unit": "м2", "price": 1},
        headers={"Authorization": pm_token},
    )
    assert r.status_code == 403


async def test_pm_cannot_update_material(async_client, pm_token):
    r = await async_client.put(
        "/prices/catalog/materials/1",
        json={"name": "Взлом", "unit": "шт", "price": 1},
        headers={"Authorization": pm_token},
    )
    assert r.status_code == 403


async def test_pm_cannot_create_work(async_client, pm_token):
    r = await async_client.post(
        "/prices/catalog/works",
        json={"name": "Своя расценка", "unit": "м2", "price": 100},
        headers={"Authorization": pm_token},
    )
    assert r.status_code == 403


async def test_pm_cannot_create_material(async_client, pm_token):
    r = await async_client.post(
        "/prices/catalog/materials",
        json={"name": "Свой материал", "unit": "шт", "price": 100},
        headers={"Authorization": pm_token},
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Чтение остаётся доступным всем — сметы считаются как раньше
# ---------------------------------------------------------------------------

async def test_pm_can_still_read_catalog(async_client, pm_token):
    r = await async_client.get("/prices/catalog", headers={"Authorization": pm_token})
    assert r.status_code == 200


async def test_pm_can_still_export_catalog(async_client, pm_token):
    r = await async_client.get(
        "/prices/catalog/export", headers={"Authorization": pm_token}
    )
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Руководителю и админу изменения по-прежнему разрешены
# ---------------------------------------------------------------------------

async def test_head_of_sales_not_forbidden(async_client, head_token):
    """404 (нет такой записи) — значит проверка прав пройдена."""
    r = await async_client.delete(
        "/prices/catalog/works/999999", headers={"Authorization": head_token}
    )
    assert r.status_code != 403


async def test_admin_not_forbidden(async_client, admin_token):
    r = await async_client.delete(
        "/prices/catalog/works/999999", headers={"Authorization": admin_token}
    )
    assert r.status_code != 403


async def test_unauthenticated_rejected(async_client):
    r = await async_client.delete("/prices/catalog/works/1")
    assert r.status_code == 401
