"""Эталонный прайс: поиск позиций, названных иначе.

Фаза 2 плана `plans/2026-09-02-etalonnyy-prays-iz-smety.md`.

Вытеснение по точному совпадению названия закрывает только половину задачи:
цена той же самой позиции, записанной в прайсе или в кеше веб-поиска другими
словами, продолжит подставляться в расчёт. Найти такие записи может только
поиск по смыслу — тот же самый, которым потом эта позиция будет искаться при
расчёте сметы, иначе «дубль» и «совпадение» считались бы по разным меркам.

Удаляет их человек. Здесь проверяется, что ему показывают: с идентификатором
(без него нечего удалять), с источником (прайс или кеш) и без самой позиции,
которая и так будет переоценена.
"""
import pytest

from app.services import price_service, reference_price
from tests.helpers.prices import axis

pytestmark = pytest.mark.asyncio


async def test_candidates_carry_id_and_source(price_db):
    """Кандидат без id бесполезен: удалять нечего. Источник решает, откуда удалять."""
    work = price_db.work("Кладка стен из кирпича", unit="м3",
                         prices={"Подрядчик": 1200.0}, vector=axis(0))
    cached = price_db.cache_work("Кладка кирпичных стен", unit="м3", price=1500.0,
                                 vector=axis(0))
    price_db.knows("Кладка стен", axis(0))
    await price_db.load()

    found = await price_service.find_duplicate_candidates("Кладка стен", "work", n=5)

    assert sorted((c["source"], str(c["id"]), c["price"]) for c in found) == [
        ("cache", str(cached.id), 1500.0),
        ("price", str(work.id), 1200.0),
    ]
    assert all(c["score"] > 0.99 for c in found)


async def test_no_vectors_gives_empty_list(price_db):
    """Векторов нет — поиск по смыслу отключён, но операция не падает."""
    price_db.work("Кладка стен из кирпича", unit="м3", prices={"Подрядчик": 1200.0})
    price_db.cache_work("Кладка кирпичных стен", unit="м3", price=1500.0)
    price_db.knows("Кладка стен", axis(0))
    await price_db.load()

    assert await price_service.find_duplicate_candidates("Кладка стен", "work") == []
    assert price_service.duplicate_vectors_ready("work") is False


async def test_matched_position_itself_is_not_a_duplicate(monkeypatch):
    """Позиция, которую и так переоценим, — не дубль: удалять её нельзя."""
    async def fake_candidates(names, kind, n=5):
        return [[
            {"source": "price", "id": 1, "name": "Кладка стен", "unit": "м3",
             "price": 1200.0, "score": 0.99},
            {"source": "price", "id": 2, "name": "Кладка кирпичных стен", "unit": "м3",
             "price": 1300.0, "score": 0.90},
        ]] * len(names)

    monkeypatch.setattr(price_service, "find_duplicate_candidates_batch", fake_candidates)
    monkeypatch.setattr(price_service, "duplicate_vectors_ready", lambda kind: True)

    result = await reference_price.find_duplicates([
        {"kind": "work", "name": "кладка  стен", "unit": "м3", "price": 1000.0},
    ])

    assert result["vectors_ready"] is True
    assert [c["id"] for c in result["candidates"]] == [2]
    assert result["candidates"][0]["for_name"] == "кладка  стен"


async def test_weak_candidate_is_not_shown(monkeypatch):
    """Совсем непохожее в список не попадает: человеку нужен выбор, а не свалка."""
    async def fake_candidates(names, kind, n=5):
        return [[
            {"source": "price", "id": 3, "name": "Покраска потолка", "unit": "м2",
             "price": 300.0, "score": 0.41},
        ]] * len(names)

    monkeypatch.setattr(price_service, "find_duplicate_candidates_batch", fake_candidates)
    monkeypatch.setattr(price_service, "duplicate_vectors_ready", lambda kind: True)

    result = await reference_price.find_duplicates([
        {"kind": "work", "name": "Кладка стен", "unit": "м3", "price": 1000.0},
    ])

    assert result["candidates"] == []


async def test_candidate_below_matching_threshold_is_still_shown(monkeypatch):
    """Порог показа ниже порога подбора цены: скрыть дубль дороже, чем показать лишнее."""
    below = price_service.SIMILARITY_THRESHOLD - 0.05

    async def fake_candidates(names, kind, n=5):
        return [[
            {"source": "cache", "id": "c-9", "name": "Кладка стен кирпичных",
             "unit": "м3", "price": 1400.0, "score": below},
        ]] * len(names)

    monkeypatch.setattr(price_service, "find_duplicate_candidates_batch", fake_candidates)
    monkeypatch.setattr(price_service, "duplicate_vectors_ready", lambda kind: True)

    result = await reference_price.find_duplicates([
        {"kind": "work", "name": "Кладка стен", "unit": "м3", "price": 1000.0},
    ])

    assert [c["id"] for c in result["candidates"]] == ["c-9"]


async def test_same_candidate_shown_once(monkeypatch):
    """Один и тот же дубль на две позиции файла — одна строка, а не две галочки."""
    async def fake_candidates(names, kind, n=5):
        return [[
            {"source": "price", "id": 5, "name": "Кладка стен кирпичных", "unit": "м3",
             "price": 1300.0, "score": 0.93},
        ]] * len(names)

    monkeypatch.setattr(price_service, "find_duplicate_candidates_batch", fake_candidates)
    monkeypatch.setattr(price_service, "duplicate_vectors_ready", lambda kind: True)

    result = await reference_price.find_duplicates([
        {"kind": "work", "name": "Кладка стен", "unit": "м3", "price": 1000.0},
        {"kind": "work", "name": "Кладка перегородок", "unit": "м3", "price": 900.0},
    ])

    assert len(result["candidates"]) == 1


async def test_batch_search_asks_the_model_once(price_db, monkeypatch):
    """Файл на сотни позиций — одна прогонка модели, а не сотня.

    Модель локальная и денег не стоит, но по вызову на позицию превращает
    предпросмотр в минуты ожидания на ровном месте.
    """
    work = price_db.work("Кладка стен из кирпича", unit="м3",
                         prices={"Подрядчик": 1200.0}, vector=axis(0))
    price_db.knows("Кладка стен", axis(0))
    await price_db.load()
    runs = []
    embed = price_db.model.embed
    monkeypatch.setattr(price_db.model, "embed", lambda texts: runs.append(1) or embed(texts))

    found = await price_service.find_duplicate_candidates_batch(
        ["Кладка стен", "Кладка перегородок", "Штукатурка"], "work", n=3,
    )

    assert len(runs) == 1
    assert len(found) == 3, "ответ — строка на каждое имя, в том же порядке"
    assert [c["id"] for c in found[0]] == [work.id]


async def test_batch_without_vectors_gives_empty_row_per_name(price_db):
    """Без векторов ответ по форме тот же — иначе вызывающий код разъедется."""
    price_db.work("Кладка стен из кирпича", unit="м3", prices={"Подрядчик": 1200.0})
    price_db.knows("Кладка стен", axis(0))
    await price_db.load()

    assert await price_service.find_duplicate_candidates_batch(
        ["Кладка стен", "Штукатурка"], "work",
    ) == [[], []]
