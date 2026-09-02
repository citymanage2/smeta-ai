"""Unit tests for embedding_service: normalize_name и generate_embeddings_batch (FastEmbed)."""
import pytest
import numpy as np
from unittest.mock import patch, MagicMock

from app.services.embedding_service import (
    normalize_name,
    generate_embeddings_batch,
    generate_embedding,
    EmbeddingUnavailableError,
)

DIM = 768


# ---------------------------------------------------------------------------
# normalize_name
# ---------------------------------------------------------------------------

def test_normalize_grade_does_not_swallow_words():
    """Слова между буквой и числом остаются на месте.

    До 02.09.2026 здесь проверялось обратное: «M defi 100» → «м100». Ради
    этого правило марок съедало любые слова между первой буквой и первым
    числом — и вместе с ними половину названий: «Пленка гидроизоляционная
    Изоспан A 1,6х50 м» и «Пленка пароизоляционная Изоспан B 1,6х50 м»
    сжимались в одно «п1,6х50 м», то есть в один вектор и один ключ прайса.
    Кейс «M defi 100» ни к одной реальной позиции не привязан, а расплатой за
    него была цена гидроизоляции у пароизоляции.
    """
    # Три слова остаются тремя. Сравнивать посимвольно тут нельзя: латинские
    # буквы, визуально совпадающие с кириллическими, заменяются на кириллицу.
    assert len(normalize_name("M defi 100").split()) == 3
    assert normalize_name("M defi 100") != "м100"

def test_normalize_m_dash_50():
    assert normalize_name("М-50") == "м50"

def test_normalize_extra_spaces():
    assert normalize_name("  Кладка  кирпичная  ") == "кладка кирпичная"

def test_normalize_empty_string():
    assert normalize_name("") == ""

def test_normalize_m100_lowercase():
    assert normalize_name("М100") == "м100"

def test_normalize_grade_written_differently_is_one_key():
    """Марка, записанная по-разному, — по-прежнему одна позиция."""
    assert normalize_name("М-100") == normalize_name("М100") == normalize_name("M 100")

def test_normalize_m100_not_equals_m50():
    assert normalize_name("М100") != normalize_name("М50")

def test_normalize_latin_m_to_cyrillic():
    assert normalize_name("M100") == "м100"


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


def test_generate_embeddings_batch_default_is_document():
    """По умолчанию input_type='search_document' → passage: prefix."""
    texts = ["текст"]
    mock_model = _make_fastembed_mock(1)

    with patch("app.services.embedding_service._get_model", return_value=mock_model):
        generate_embeddings_batch(texts)

    call_args = mock_model.embed.call_args[0][0]
    assert call_args[0].startswith("passage: ")


def test_generate_embedding_single_returns_vector():
    """generate_embedding возвращает первый вектор из батча."""
    mock_model = _make_fastembed_mock(1)

    with patch("app.services.embedding_service._get_model", return_value=mock_model):
        result = generate_embedding("тест", input_type="search_query")

    assert len(result) == DIM


def test_model_unavailable_raises():
    """Если fastembed не установлен → EmbeddingUnavailableError."""
    with patch("app.services.embedding_service._get_model",
               side_effect=EmbeddingUnavailableError("Библиотека fastembed не установлена")):
        with pytest.raises(EmbeddingUnavailableError, match="fastembed"):
            generate_embedding("тест")
