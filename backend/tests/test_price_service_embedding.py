"""Unit tests for _embedding_match_work / _embedding_match_material (8.3).

Проверяют три сценария:
- similarity >= 0.82 → возвращает элемент кэша
- similarity < 0.82  → возвращает None
- _works_embeddings is None → возвращает None (без вызова OpenAI)
"""
import pytest
import numpy as np
from unittest.mock import patch
import app.services.price_service as ps

DIM = 1024


def _unit_vec(idx: int) -> list[float]:
    """Единичный вектор с 1 в позиции idx — все остальные 0."""
    v = [0.0] * DIM
    v[idx] = 1.0
    return v


@pytest.fixture(autouse=True)
def restore_price_service_state():
    """Сохранить и восстановить глобальные переменные price_service после каждого теста."""
    we = ps._works_embeddings
    me = ps._materials_embeddings
    wrn = ps._works_row_norms
    mrn = ps._materials_row_norms
    wc = ps._works_cache[:]
    mc = ps._materials_cache[:]
    yield
    ps._works_embeddings = we
    ps._materials_embeddings = me
    ps._works_row_norms = wrn
    ps._materials_row_norms = mrn
    ps._works_cache[:] = wc
    ps._materials_cache[:] = mc


def _inject_works(vectors: list[list[float]], items: list[dict]) -> None:
    matrix = np.array(vectors, dtype=np.float32)
    ps._works_embeddings = matrix
    ps._works_row_norms = np.linalg.norm(matrix, axis=1)
    ps._works_cache[:] = items


def _inject_materials(vectors: list[list[float]], items: list[dict]) -> None:
    matrix = np.array(vectors, dtype=np.float32)
    ps._materials_embeddings = matrix
    ps._materials_row_norms = np.linalg.norm(matrix, axis=1)
    ps._materials_cache[:] = items


# ---------------------------------------------------------------------------
# _embedding_match_work
# ---------------------------------------------------------------------------

async def test_embedding_match_work_returns_item_above_threshold():
    """similarity=1.0 (одинаковые векторы) → возвращает элемент кэша."""
    vec = _unit_vec(0)
    _inject_works([vec], [{"name": "Кладка кирпичная", "min_price": 500.0, "source": "Прайс"}])

    with patch("app.services.embedding_service.generate_embedding", return_value=vec):
        result = await ps._embedding_match_work("Кладка кирпичная")

    assert result is not None
    assert result["name"] == "Кладка кирпичная"


async def test_embedding_match_work_returns_none_below_threshold():
    """Ортогональные векторы (similarity=0) → None."""
    _inject_works([_unit_vec(0)], [{"name": "Кладка", "min_price": 500.0}])

    # Вектор в другом направлении → similarity = 0 < 0.82
    with patch("app.services.embedding_service.generate_embedding", return_value=_unit_vec(1)):
        result = await ps._embedding_match_work("Бетонирование")

    assert result is None


async def test_embedding_match_work_no_embeddings_returns_none():
    """_works_embeddings is None → None без вызова OpenAI."""
    ps._works_embeddings = None
    ps._works_row_norms = None

    # Если бы generate_embedding вызывался — тест упал бы, но он не должен вызываться
    result = await ps._embedding_match_work("Кладка")
    assert result is None


async def test_embedding_match_work_picks_best_match():
    """При нескольких векторах выбирается лучшее совпадение."""
    vec_a = _unit_vec(0)  # совпадает с запросом
    vec_b = _unit_vec(1)  # не совпадает
    _inject_works(
        [vec_b, vec_a],
        [
            {"name": "Штукатурка", "min_price": 200.0},
            {"name": "Кладка кирпичная", "min_price": 500.0},
        ],
    )

    with patch("app.services.embedding_service.generate_embedding", return_value=vec_a):
        result = await ps._embedding_match_work("Кладка кирпичная")

    assert result is not None
    assert result["name"] == "Кладка кирпичная"


# ---------------------------------------------------------------------------
# _embedding_match_material
# ---------------------------------------------------------------------------

async def test_embedding_match_material_returns_price_above_threshold():
    """similarity=1.0 → возвращает цену материала."""
    vec = _unit_vec(5)
    _inject_materials([vec], [{"name": "Кирпич М150", "price": 12.5}])

    with patch("app.services.embedding_service.generate_embedding", return_value=vec):
        result = await ps._embedding_match_material("Кирпич М150")

    assert result == 12.5


async def test_embedding_match_material_returns_none_below_threshold():
    """Ортогональные векторы → None."""
    _inject_materials([_unit_vec(5)], [{"name": "Кирпич М150", "price": 12.5}])

    with patch("app.services.embedding_service.generate_embedding", return_value=_unit_vec(6)):
        result = await ps._embedding_match_material("Цемент М400")

    assert result is None


async def test_embedding_match_material_no_embeddings_returns_none():
    """_materials_embeddings is None → None."""
    ps._materials_embeddings = None
    ps._materials_row_norms = None

    result = await ps._embedding_match_material("Кирпич")
    assert result is None
