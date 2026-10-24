"""Unit tests for embedding_service: generate_embeddings_batch (FastEmbed).

Нормализация имени (`normalize_name`) — в test_normalize_name_collisions.py.
"""
import pytest
import numpy as np
from unittest.mock import patch, MagicMock

from app.services.embedding_service import (
    generate_embeddings_batch,
    generate_embedding,
    EmbeddingUnavailableError,
)

DIM = 768


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fastembed_mock(count: int, dim: int = DIM) -> MagicMock:
    """Возвращает mock TextEmbedding с правильным форматом ответа."""
    mock_model = MagicMock()
    mock_model.embed.return_value = iter([
        np.array([float(i % 10) / 10.0 + 0.1] * dim) for i in range(count)
    ])
    return mock_model


# ---------------------------------------------------------------------------
# generate_embeddings_batch (FastEmbed mock)
# ---------------------------------------------------------------------------

def test_generate_embeddings_batch_success():
    """Успешная генерация: возвращает вектор для каждого текста."""
    texts = ["кладка кирпичная", "штукатурка", "бетонирование"]
    mock_model = _make_fastembed_mock(len(texts))

    with patch("app.services.embedding_service._get_model", return_value=mock_model):
        result = generate_embeddings_batch(texts)

    assert len(result) == 3
    assert all(len(v) == DIM for v in result)
    mock_model.embed.assert_called_once()


def test_generate_embeddings_batch_returns_in_order():
    """Векторы возвращаются в том же порядке, что входные тексты."""
    texts = ["первый", "второй", "третий"]
    mock_model = MagicMock()
    mock_model.embed.return_value = iter([
        np.array([0.0] * DIM),
        np.array([1.0] * DIM),
        np.array([2.0] * DIM),
    ])

    with patch("app.services.embedding_service._get_model", return_value=mock_model):
        result = generate_embeddings_batch(texts)

    assert result[0][0] == 0.0
    assert result[1][0] == 1.0
    assert result[2][0] == 2.0


def test_generate_embeddings_batch_empty_input():
    """Пустой список → пустой результат без вызовов API."""
    result = generate_embeddings_batch([])
    assert result == []


def test_generate_embeddings_batch_api_error_raises():
    """Любая ошибка FastEmbed → EmbeddingUnavailableError."""
    mock_model = MagicMock()
    mock_model.embed.side_effect = RuntimeError("модель не загружена")

    with patch("app.services.embedding_service._get_model", return_value=mock_model):
        with pytest.raises(EmbeddingUnavailableError):
            generate_embeddings_batch(["тест"])


def test_generate_embeddings_batch_passage_prefix():
    """search_document → 'passage: ' prefix передаётся в модель."""
    texts = ["документ"]
    mock_model = _make_fastembed_mock(1)

    with patch("app.services.embedding_service._get_model", return_value=mock_model):
        generate_embeddings_batch(texts, input_type="search_document")

    call_args = mock_model.embed.call_args[0][0]
    assert call_args[0].startswith("passage: ")


def test_generate_embeddings_batch_query_prefix():
    """search_query → 'query: ' prefix передаётся в модель."""
    texts = ["запрос"]
    mock_model = _make_fastembed_mock(1)

    with patch("app.services.embedding_service._get_model", return_value=mock_model):
        generate_embeddings_batch(texts, input_type="search_query")

    call_args = mock_model.embed.call_args[0][0]
    assert call_args[0].startswith("query: ")


def test_generate_embedding_single_returns_vector():
    """generate_embedding возвращает первый вектор из батча."""
    mock_model = _make_fastembed_mock(1)

    with patch("app.services.embedding_service._get_model", return_value=mock_model):
        result = generate_embedding("тест", input_type="search_query")

    assert len(result) == DIM
