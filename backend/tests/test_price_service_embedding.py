"""Подбор цены по смыслу: позиция находится выше порога похожести и не находится ниже.

Прайс и векторы лежат в тестовой БД, кеш подбора собирает `load_cache` — как в
проде; подменена только модель эмбеддингов (фикстура `price_db`).
"""
from app.services import price_service
from tests.helpers.prices import axis, similar


async def test_works_found_above_threshold_and_best_wins(price_db):
    threshold = price_service.SIMILARITY_THRESHOLD
    price_db.work("Кладка кирпичная", unit="м3", prices={"Подрядчик": 5200.0}, vector=axis(0))
    price_db.work("Штукатурка стен", unit="м2", prices={"Подрядчик": 450.0}, vector=axis(1))
    # Ближе к кладке (0,9), но похож и на штукатурку (0,44) — берётся лучшее.
    price_db.knows("Кладка стен из кирпича", similar(0.9, to=0, via=1))
    price_db.knows("Устройство стяжки", similar(threshold - 0.01, to=1))
    price_db.knows("Монтаж окон", axis(5))
    await price_db.load()

    found = await price_service.batch_embedding_match_works(
        ["Кладка стен из кирпича", "Устройство стяжки", "Монтаж окон"]
    )

    assert found[0]["name"] == "Кладка кирпичная"
    assert found[0]["min_price"] == 5200.0
    assert found[0]["unit"] == "м3"
    assert found[1] is None, "похожесть чуть ниже порога — позиция не найдена"
    assert found[2] is None


async def test_materials_found_by_mark_spelling_and_not_below_threshold(price_db):
    threshold = price_service.SIMILARITY_THRESHOLD
    price_db.material("Кирпич М150", unit="шт", price=12.5, vector=axis(5))
    price_db.knows("Цемент М400", similar(threshold - 0.01, to=5))
    await price_db.load()

    # «М-150» и «М150» — одна марка: запрос получает вектор той же позиции.
    found = await price_service.batch_embedding_match_material_rows(["Кирпич М-150", "Цемент М400"])

    assert found[0]["name"] == "Кирпич М150"
    assert found[0]["price"] == 12.5
    assert found[0]["unit"] == "шт"
    assert found[1] is None
