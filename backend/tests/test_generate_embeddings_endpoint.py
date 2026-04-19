"""Integration tests for POST /admin/price-lists/{type}/generate-embeddings (8.4).

Проверяет:
- pending → ready при успешной генерации (с mock OpenAI)
- pending → failed при ошибке OpenAI (HTTP 200, не 500)
- 404 если прайс-лист не найден
- 400 при неверном типе
"""
import pytest
from unittest.mock import patch, AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.models.price import PriceWork
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


async def test_generate_embeddings_not_found_returns_404(async_client, admin_token):
    """POST generate-embeddings: нет прайс-листа → 404."""
    resp = await async_client.post(
        "/admin/price-lists/works/generate-embeddings",
        headers={"Authorization": admin_token},
    )
    assert resp.status_code == 404


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
