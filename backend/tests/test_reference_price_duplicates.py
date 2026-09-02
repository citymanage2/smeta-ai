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
import numpy as np
import pytest

from app.services import price_service, reference_price

pytestmark = pytest.mark.asyncio


def _vec(*values: float) -> list[float]:
    return list(values)


def _install_price_vectors(monkeypatch, rows: list[dict], vectors: list[list[float]]):
    """Подсунуть прайсу работ готовые векторы вместо настоящей модели."""
    matrix = np.array(vectors, dtype=np.float32)
    monkeypatch.setattr(price_service, "_works_cache", rows)
    monkeypatch.setattr(price_service, "_works_embeddings", matrix)
    monkeypatch.setattr(price_service, "_works_row_norms", np.linalg.norm(matrix, axis=1))
    monkeypatch.setattr(price_service, "_works_index_map", list(range(len(rows))))


def _install_cache_vectors(monkeypatch, rows: list[dict], vectors: list[list[float]]):
    matrix = np.array(vectors, dtype=np.float32)
    monkeypatch.setattr(price_service, "_cache_works_cache", rows)
    monkeypatch.setattr(price_service, "_cache_works_embeddings", matrix)
    monkeypatch.setattr(price_service, "_cache_works_row_norms", np.linalg.norm(matrix, axis=1))
    monkeypatch.setattr(price_service, "_cache_works_index_map", list(range(len(rows))))


def _fake_query_vector(monkeypatch, vector: list[float]):
    from app.services import embedding_service

    monkeypatch.setattr(
        embedding_service, "generate_embedding", lambda text, input_type="search_document": vector
    )


async def test_candidates_carry_id_and_source(monkeypatch):
    """Кандидат без id бесполезен: удалять нечего. Источник решает, откуда удалять."""
    _install_price_vectors(
        monkeypatch,
        [{"id": 7, "name": "Кладка стен из кирпича", "unit": "м3", "min_price": 1200.0}],
        [_vec(1.0, 0.0)],
    )
    _install_cache_vectors(
        monkeypatch,
        [{"id": "c-1", "name": "Кладка кирпичных стен", "unit": "м3", "price": 1500.0}],
        [_vec(1.0, 0.0)],
    )
    _fake_query_vector(monkeypatch, _vec(1.0, 0.0))

    found = await price_service.find_duplicate_candidates("Кладка стен", "work", n=5)

    assert [(c["source"], c["id"], c["price"]) for c in found] == [
        ("price", 7, 1200.0),
        ("cache", "c-1", 1500.0),
    ]
    assert all(c["score"] > 0.99 for c in found)


async def test_no_vectors_gives_empty_list(monkeypatch):
    """Векторов нет — поиск по смыслу отключён, но операция не падает."""
    monkeypatch.setattr(price_service, "_works_embeddings", None)
    monkeypatch.setattr(price_service, "_cache_works_embeddings", None)

    assert await price_service.find_duplicate_candidates("Кладка стен", "work") == []
    assert price_service.duplicate_vectors_ready("work") is False


async def test_matched_position_itself_is_not_a_duplicate(monkeypatch):
    """Позиция, которую и так переоценим, — не дубль: удалять её нельзя."""
    async def fake_candidates(name, kind, n=5):
        return [
            {"source": "price", "id": 1, "name": "Кладка стен", "unit": "м3",
             "price": 1200.0, "score": 0.99},
            {"source": "price", "id": 2, "name": "Кладка кирпичных стен", "unit": "м3",
             "price": 1300.0, "score": 0.90},
        ]

    monkeypatch.setattr(price_service, "find_duplicate_candidates", fake_candidates)
    monkeypatch.setattr(price_service, "duplicate_vectors_ready", lambda kind: True)

    result = await reference_price.find_duplicates([
        {"kind": "work", "name": "кладка  стен", "unit": "м3", "price": 1000.0},
    ])

    assert result["vectors_ready"] is True
    assert [c["id"] for c in result["candidates"]] == [2]
    assert result["candidates"][0]["for_name"] == "кладка  стен"


async def test_weak_candidate_is_not_shown(monkeypatch):
    """Совсем непохожее в список не попадает: человеку нужен выбор, а не свалка."""
    async def fake_candidates(name, kind, n=5):
        return [
            {"source": "price", "id": 3, "name": "Покраска потолка", "unit": "м2",
             "price": 300.0, "score": 0.41},
        ]

    monkeypatch.setattr(price_service, "find_duplicate_candidates", fake_candidates)
    monkeypatch.setattr(price_service, "duplicate_vectors_ready", lambda kind: True)

    result = await reference_price.find_duplicates([
        {"kind": "work", "name": "Кладка стен", "unit": "м3", "price": 1000.0},
    ])

    assert result["candidates"] == []


async def test_candidate_below_matching_threshold_is_still_shown(monkeypatch):
    """Порог показа ниже порога подбора цены: скрыть дубль дороже, чем показать лишнее."""
    below = price_service.SIMILARITY_THRESHOLD - 0.05

    async def fake_candidates(name, kind, n=5):
        return [
            {"source": "cache", "id": "c-9", "name": "Кладка стен кирпичных",
             "unit": "м3", "price": 1400.0, "score": below},
        ]

    monkeypatch.setattr(price_service, "find_duplicate_candidates", fake_candidates)
    monkeypatch.setattr(price_service, "duplicate_vectors_ready", lambda kind: True)

    result = await reference_price.find_duplicates([
        {"kind": "work", "name": "Кладка стен", "unit": "м3", "price": 1000.0},
    ])

    assert [c["id"] for c in result["candidates"]] == ["c-9"]


async def test_same_candidate_shown_once(monkeypatch):
    """Один и тот же дубль на две позиции файла — одна строка, а не две галочки."""
    async def fake_candidates(name, kind, n=5):
        return [
            {"source": "price", "id": 5, "name": "Кладка стен кирпичных", "unit": "м3",
             "price": 1300.0, "score": 0.93},
        ]

    monkeypatch.setattr(price_service, "find_duplicate_candidates", fake_candidates)
    monkeypatch.setattr(price_service, "duplicate_vectors_ready", lambda kind: True)

    result = await reference_price.find_duplicates([
        {"kind": "work", "name": "Кладка стен", "unit": "м3", "price": 1000.0},
        {"kind": "work", "name": "Кладка перегородок", "unit": "м3", "price": 900.0},
    ])

    assert len(result["candidates"]) == 1
