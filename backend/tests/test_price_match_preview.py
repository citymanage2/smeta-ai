"""Диагностика «почему позиция не нашлась в прайсе».

30.07.2026: из 1220 позиций сметы по прайсу нашлось 16. Снаружи это выглядит
одинаково для трёх разных причин — пустой каталог, отсутствие векторов и слишком
высокий порог похожести. Эндпоинт показывает, что именно отвечает прайс на
конкретное название и с какой похожестью.
"""
import pytest

from app.services import price_service
from tests.helpers.prices import axis, similar

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


async def test_no_vectors_says_so(async_client, admin_token, price_db):
    """Векторов нет → это и есть ответ, а не «позиции нет в прайсе»."""
    price_db.work("Устройство стяжек", unit="м2", prices={"Подрядчик": 350.0})  # без вектора
    await price_db.load()

    r = await async_client.post(
        "/prices/match-preview",
        json={"name": "Устройство стяжек", "kind": "work"},
        headers={"Authorization": admin_token},
    )
    data = r.json()
    assert data["vectors_ready"] is False
    assert data["candidates"] == []
    assert "векторов" in data["hint"]


@pytest.mark.parametrize(
    "kind, similarity, matched, hint_word",
    [
        # Похожесть выше порога → «нашлась бы».
        ("work", 0.91, True, "нашлась"),
        # Чуть ниже порога → подсказка про порог, а не «позиции нет».
        ("work", price_service.SIMILARITY_THRESHOLD - 0.03, False, "порог"),
        # Лучший кандидат про другое → позицию надо добавлять в прайс.
        ("material", 0.31, False, "Похожих позиций"),
    ],
)
async def test_answer_follows_similarity(
    async_client, admin_token, price_db, kind, similarity, matched, hint_word
):
    """Что ответит прайс, решает похожесть векторов позиции и запроса."""
    if kind == "work":
        price_db.work("Устройство стяжек цементных", unit="м2",
                      prices={"Подрядчик": 350.0}, vector=axis(0))
    else:
        price_db.material("Окраска стен", unit="м2", price=100.0, vector=axis(0))
    price_db.knows("Запрос из сметы", similar(similarity, to=0))
    await price_db.load()

    r = await async_client.post(
        "/prices/match-preview",
        json={"name": "Запрос из сметы", "kind": kind},
        headers={"Authorization": admin_token},
    )

    data = r.json()
    assert data["vectors_ready"] is True
    assert data["catalog_size"] == 1
    assert data["matched"] is matched
    best = data["candidates"][0]
    assert best["score"] == pytest.approx(similarity, abs=1e-3)
    assert best["would_match"] is matched
    if kind == "work":
        assert best["price"] == 350.0
    assert hint_word in data["hint"]


@pytest.mark.parametrize("kind", ["work", "material"])
async def test_candidate_shows_recorded_price(async_client, admin_token, price_db, kind):
    """Цена кандидата — та, что записана в прайсе, и у работы, и у материала.

    До 25.10.2026 у материала всегда стоял прочерк: поиск кладёт цену в
    `min_price`, а эндпоинт читал у материала `price`.
    """
    if kind == "work":
        price_db.work("Монтаж кабеля", unit="м", prices={"Подрядчик": 87.5}, vector=axis(0))
    else:
        price_db.material("Кабель ВВГнг 3х2,5", unit="м", price=87.5, vector=axis(0))
    price_db.knows("Кабель", similar(0.95, to=0))
    await price_db.load()

    r = await async_client.post(
        "/prices/match-preview",
        json={"name": "Кабель", "kind": kind},
        headers={"Authorization": admin_token},
    )

    assert r.status_code == 200, r.text
    (best,) = r.json()["candidates"]
    assert best["price"] == 87.5
    assert best["unit"] == "м"
