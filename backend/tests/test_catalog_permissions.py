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
import pytest_asyncio
from sqlalchemy import select

from app.models.price import PriceMaterial, PriceWork
from app.utils.auth import create_access_token

pytestmark = pytest.mark.asyncio


def _token(role: str, user_id: int) -> str:
    return f"Bearer {create_access_token(user_id, role)}"


@pytest.fixture
def pm_token() -> str:
    """Рядовой исполнитель — та роль, которой каталог менять нельзя."""
    return _token("project_manager", 42)


@pytest_asyncio.fixture
async def catalog(price_db) -> dict:
    """Каталог из одной работы и одного материала; id — для адресов правки."""
    work = price_db.work("Кладка стен", unit="м3", prices={"Подрядчик": 1000.0})
    material = price_db.material("Кирпич", unit="шт", price=25.0)
    await price_db.load()
    return {"work": work.id, "material": material.id}


async def _catalog_rows(db) -> set:
    """Каталог так, как по нему считаются сметы: позиции и их цены."""
    db.expire_all()
    works = (await db.execute(select(PriceWork))).scalars().all()
    materials = (await db.execute(select(PriceMaterial))).scalars().all()
    return (
        {("work", w.name, w.unit, tuple(sorted((w.prices or {}).items()))) for w in works}
        | {("material", m.name, m.unit, m.price) for m in materials}
    )


# Все изменяющие операции каталога: (метод, адрес, тело).
CHANGES = [
    pytest.param("post", "/prices/catalog/works",
                 {"name": "Своя расценка", "unit": "м2", "prices": {"Подрядчик": 100}},
                 id="create-work"),
    pytest.param("post", "/prices/catalog/materials",
                 {"name": "Свой материал", "unit": "шт", "price": 100}, id="create-material"),
    pytest.param("put", "/prices/catalog/works/{work}", {"prices": {"Подрядчик": 1}},
                 id="update-work"),
    pytest.param("put", "/prices/catalog/materials/{material}", {"price": 1},
                 id="update-material"),
    pytest.param("delete", "/prices/catalog/works/{work}", None, id="delete-work"),
    pytest.param("delete", "/prices/catalog/materials/{material}", None, id="delete-material"),
]


async def _change(async_client, token, catalog, method, url, body):
    return await async_client.request(
        method, url.format(**catalog), json=body, headers={"Authorization": token},
    )


# ---------------------------------------------------------------------------
# Изменяющие операции закрыты для рядового пользователя
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method, url, body", CHANGES)
async def test_pm_cannot_change_catalog(
    async_client, pm_token, catalog, db_session, method, url, body,
):
    """403 — и каталог, по которому считаются все сметы, не тронут."""
    before = await _catalog_rows(db_session)

    r = await _change(async_client, pm_token, catalog, method, url, body)

    assert r.status_code == 403
    assert await _catalog_rows(db_session) == before


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

@pytest.mark.parametrize("role, user_id", [("head_of_sales", 7), ("admin", 2)])
@pytest.mark.parametrize("method, url, body", CHANGES)
async def test_manager_changes_catalog(
    async_client, catalog, db_session, role, user_id, method, url, body,
):
    before = await _catalog_rows(db_session)

    r = await _change(async_client, _token(role, user_id), catalog, method, url, body)

    assert r.status_code in (200, 201, 204), r.text
    assert await _catalog_rows(db_session) != before


async def test_unauthenticated_rejected(async_client):
    r = await async_client.delete("/prices/catalog/works/1")
    assert r.status_code == 401
