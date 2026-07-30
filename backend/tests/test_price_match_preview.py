"""Диагностика «почему позиция не нашлась в прайсе».

30.07.2026: из 1220 позиций сметы по прайсу нашлось 16. Снаружи это выглядит
одинаково для трёх разных причин — пустой каталог, отсутствие векторов и слишком
высокий порог похожести. Эндпоинт показывает, что именно отвечает прайс на
конкретное название и с какой похожестью.
"""
import pytest

from app.services import price_service

pytestmark = pytest.mark.asyncio


async def test_requires_manager(async_client, user_token):
    r = await async_client.post(
        "/prices/match-preview",
        json={"name": "Устройство стяжек", "kind": "work"},
        headers={"Authorization": user_token},
    )
    assert r.status_code == 403


async def test_empty_name_rejected(async_client, admin_token):
    r = await async_client.post(
        "/prices/match-preview",
        json={"name": "   ", "kind": "work"},
        headers={"Authorization": admin_token},
    )
    assert r.status_code == 400


async def test_no_vectors_says_so(async_client, admin_token, monkeypatch):
    """Векторов нет → это и есть ответ, а не «позиции нет в прайсе»."""
    monkeypatch.setattr(price_service, "_works_embeddings", None)

    r = await async_client.post(
        "/prices/match-preview",
        json={"name": "Устройство стяжек", "kind": "work"},
        headers={"Authorization": admin_token},
    )
    data = r.json()
    assert data["vectors_ready"] is False
    assert data["candidates"] == []
    assert "векторов" in data["hint"]


async def test_match_found(async_client, admin_token, monkeypatch):
    """Похожесть выше порога → «нашлась бы»."""
    async def fake_top(name, n=5):
        return [{"text": "Устройство стяжек цементных", "score": 0.91, "unit": "м2", "min_price": 350.0}]

    monkeypatch.setattr(price_service, "find_top_n_works", fake_top)
    monkeypatch.setattr(price_service, "_works_embeddings", object())
    monkeypatch.setattr(price_service, "_works_cache", [{"name": "x"}])

    r = await async_client.post(
        "/prices/match-preview",
        json={"name": "Устройство стяжек", "kind": "work"},
        headers={"Authorization": admin_token},
    )
    data = r.json()
    assert data["matched"] is True
    assert data["candidates"][0]["would_match"] is True
    assert data["candidates"][0]["price"] == 350.0
    assert "нашлась" in data["hint"]


async def test_just_below_threshold_suggests_threshold(async_client, admin_token, monkeypatch):
    """Чуть ниже порога → подсказка про порог, а не «позиции нет»."""
    threshold = price_service.SIMILARITY_THRESHOLD

    async def fake_top(name, n=5):
        return [{"text": "Стяжка цементная", "score": threshold - 0.03, "unit": "м2", "min_price": 300.0}]

    monkeypatch.setattr(price_service, "find_top_n_works", fake_top)
    monkeypatch.setattr(price_service, "_works_embeddings", object())
    monkeypatch.setattr(price_service, "_works_cache", [{"name": "x"}])

    r = await async_client.post(
        "/prices/match-preview",
        json={"name": "Устройство стяжек", "kind": "work"},
        headers={"Authorization": admin_token},
    )
    data = r.json()
    assert data["matched"] is False
    assert "порог" in data["hint"]


async def test_nothing_similar(async_client, admin_token, monkeypatch):
    """Лучший кандидат про другое → позицию надо добавлять в прайс."""
    async def fake_top(name, n=5):
        return [{"text": "Окраска стен", "score": 0.31, "unit": "м2", "price": 100.0}]

    monkeypatch.setattr(price_service, "find_top_n_materials", fake_top)
    monkeypatch.setattr(price_service, "_materials_embeddings", object())
    monkeypatch.setattr(price_service, "_materials_cache", [{"name": "x"}])

    r = await async_client.post(
        "/prices/match-preview",
        json={"name": "Блоки оконные пластиковые", "kind": "material"},
        headers={"Authorization": admin_token},
    )
    data = r.json()
    assert data["matched"] is False
    assert "Похожих позиций" in data["hint"]
