"""Integration tests for POST /admin/price-lists/{type}/generate-embeddings (8.4).

Проверяет:
- pending → ready при успешной генерации (с mock OpenAI)
- pending → failed при ошибке OpenAI (HTTP 200, не 500)
- пересборка без записи о загруженном файле и для кеша веб-поиска
- 400 при неверном типе
"""
import pytest
from unittest.mock import patch, AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.models.price import PriceWork
from app.models.price_cache import PriceCacheMaterial, PriceCacheWork
from app.models.price_list import PriceList
from app.services.embedding_service import EmbeddingUnavailableError


FAKE_VECTOR = [0.1] * 1024


@pytest.fixture
async def seed_works_price_list(db_session: AsyncSession):
    """Прайс-лист работ с 3 строками, статус pending."""
    pl = PriceList(
        type="works",
        filename="test_works.xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        content=b"fake-excel",
        embedding_status="pending",
    )
    db_session.add(pl)
    await db_session.flush()

    for i in range(3):
        db_session.add(PriceWork(
            name=f"Кладка вид {i}",
            unit="м2",
            prices={},
            min_price=float(100 + i * 10),
        ))
    await db_session.commit()
    yield pl

    await db_session.execute(text("DELETE FROM price_works"))
    await db_session.execute(text("DELETE FROM price_lists"))
    await db_session.commit()


async def test_generate_embeddings_status_pending_to_ready(
    async_client, admin_token, seed_works_price_list, db_session: AsyncSession
):
    """POST generate-embeddings: pending → ready, updated=3."""
    mock_ps = AsyncMock()
    mock_ps.load_cache = AsyncMock()
    with patch(
        "app.routers.admin.generate_embeddings_batch",
        return_value=[FAKE_VECTOR] * 3,
    ), patch("app.routers.admin.price_service", mock_ps):
        resp = await async_client.post(
            "/admin/price-lists/works/generate-embeddings",
            headers={"Authorization": admin_token},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ready"
    assert data["updated"] == 3


async def test_generate_embeddings_status_failed_on_openai_error(
    async_client, admin_token, seed_works_price_list
):
    """POST generate-embeddings: ошибка OpenAI → status=failed, HTTP 200 (не 500)."""
    with patch(
        "app.routers.admin.generate_embeddings_batch",
        side_effect=EmbeddingUnavailableError("API недоступен"),
    ):
        resp = await async_client.post(
            "/admin/price-lists/works/generate-embeddings",
            headers={"Authorization": admin_token},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert "error" in data
    assert data["error"] is not None


async def test_generate_embeddings_works_without_uploaded_file(
    async_client, admin_token, db_session: AsyncSession
):
    """Записи о загруженном файле нет — векторы всё равно пересобираются.

    До 02.09.2026 здесь был 404: эндпоинт искал строку в `price_lists` и без
    неё отказывался работать. Но прайс наполняется не только файлом — ещё
    каталогом и кнопкой «В прайс» из редактора, и у такого прайса записи о
    файле нет. Пересобрать векторы после правки нормализации имён было бы
    нечем — при том, что именно это и нужно сделать.
    """
    db_session.add(PriceWork(name="Кладка без файла", unit="м2", prices={}, min_price=100.0))
    await db_session.commit()

    mock_ps = AsyncMock()
    mock_ps.load_cache = AsyncMock()
    with patch(
        "app.routers.admin.generate_embeddings_batch", return_value=[FAKE_VECTOR],
    ), patch("app.routers.admin.price_service", mock_ps):
        resp = await async_client.post(
            "/admin/price-lists/works/generate-embeddings",
            headers={"Authorization": admin_token},
        )

    assert resp.status_code == 200
    assert resp.json()["updated"] == 1

    await db_session.execute(text("DELETE FROM price_works"))
    await db_session.commit()


async def test_generate_embeddings_for_web_search_cache(
    async_client, admin_token, db_session: AsyncSession
):
    """Кеш веб-поиска пересобирается тоже.

    При расчёте сметы он идёт сразу после прайса и подставляет цену наравне с
    ним — значит и вектор у него должен быть посчитан по тем же правилам.
    """
    db_session.add(PriceCacheWork(name="Кладка из кеша", unit="м2", price=100.0))
    db_session.add(PriceCacheMaterial(name="Кирпич из кеша", unit="шт", price=25.0))
    await db_session.commit()

    mock_ps = AsyncMock()
    mock_ps.load_cache = AsyncMock()
    with patch(
        "app.routers.admin.generate_embeddings_batch", return_value=[FAKE_VECTOR, FAKE_VECTOR],
    ), patch("app.routers.admin.price_service", mock_ps):
        resp = await async_client.post(
            "/admin/price-lists/cache/generate-embeddings",
            headers={"Authorization": admin_token},
        )

    assert resp.status_code == 200
    assert resp.json()["updated"] == 2

    await db_session.execute(text("DELETE FROM price_cache_works"))
    await db_session.execute(text("DELETE FROM price_cache_materials"))
    await db_session.commit()


async def test_generate_embeddings_invalid_type_returns_400(async_client, admin_token):
    """POST generate-embeddings: неверный тип прайс-листа → 400."""
    resp = await async_client.post(
        "/admin/price-lists/invalid_type/generate-embeddings",
        headers={"Authorization": admin_token},
    )
    assert resp.status_code == 400


async def test_generate_embeddings_requires_admin(async_client, user_token):
    """POST generate-embeddings: без прав администратора → 403."""
    resp = await async_client.post(
        "/admin/price-lists/works/generate-embeddings",
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 403
