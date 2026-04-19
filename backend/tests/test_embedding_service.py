"""Unit tests for embedding_service: normalize_name и generate_embeddings_batch (Cohere)."""
import sys
import pytest
from unittest.mock import patch, MagicMock

# Мокируем cohere до импорта embedding_service
_cohere_mock = MagicMock()
sys.modules.setdefault("cohere", _cohere_mock)

from app.services.embedding_service import (
    normalize_name,
    generate_embeddings_batch,
    generate_embedding,
    EmbeddingUnavailableError,
)

DIM = 1024


# ---------------------------------------------------------------------------
# normalize_name (без изменений — тесты должны пройти)
# ---------------------------------------------------------------------------

def test_normalize_m_defi_100():
    assert normalize_name("M defi 100") == "м100"

def test_normalize_m_dash_50():
    assert normalize_name("М-50") == "м50"

def test_normalize_extra_spaces():
    assert normalize_name("  Кладка  кирпичная  ") == "кладка кирпичная"

def test_normalize_empty_string():
    assert normalize_name("") == ""

def test_normalize_m100_lowercase():
    assert normalize_name("М100") == "м100"

def test_normalize_m_defi_100_equals_m100():
    assert normalize_name("M defi 100") == normalize_name("М100")

def test_normalize_m100_not_equals_m50():
    assert normalize_name("М100") != normalize_name("М50")

def test_normalize_latin_m_to_cyrillic():
    assert normalize_name("M100") == "м100"


# ---------------------------------------------------------------------------
# generate_embeddings_batch (Cohere mock)
# ---------------------------------------------------------------------------

def _make_cohere_client_mock(count: int, dim: int = DIM) -> MagicMock:
    """Возвращает mock клиента Cohere с правильным форматом ответа."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.embeddings.float_ = [
        [float(i % 10) / 10.0 + 0.1] * dim for i in range(count)
    ]
    mock_client.embed.return_value = mock_response
    return mock_client


def test_generate_embeddings_batch_success():
    """Успешная генерация: возвращает вектор для каждого текста."""
    texts = ["кладка кирпичная", "штукатурка", "бетонирование"]
    mock_client = _make_cohere_client_mock(len(texts))

    with patch("app.services.embedding_service._get_cohere_client", return_value=mock_client):
        result = generate_embeddings_batch(texts)

    assert len(result) == 3
    assert all(len(v) == DIM for v in result)
    mock_client.embed.assert_called_once()


def test_generate_embeddings_batch_empty_input():
    """Пустой список → пустой результат без вызовов API."""
    result = generate_embeddings_batch([])
    assert result == []


def test_generate_embeddings_batch_api_error_raises():
    """Любая ошибка Cohere API → EmbeddingUnavailableError."""
    mock_client = MagicMock()
    mock_client.embed.side_effect = RuntimeError("connection timeout")

    with patch("app.services.embedding_service._get_cohere_client", return_value=mock_client):
        with pytest.raises(EmbeddingUnavailableError):
            generate_embeddings_batch(["тест"])


def test_generate_embeddings_batch_passes_input_type():
    """input_type передаётся в Cohere API."""
    texts = ["запрос"]
    mock_client = _make_cohere_client_mock(1)

    with patch("app.services.embedding_service._get_cohere_client", return_value=mock_client):
        generate_embeddings_batch(texts, input_type="search_query")

    call_kwargs = mock_client.embed.call_args.kwargs
    assert call_kwargs["input_type"] == "search_query"


def test_generate_embeddings_batch_default_input_type_is_document():
    """По умолчанию input_type='search_document'."""
    texts = ["документ"]
    mock_client = _make_cohere_client_mock(1)

    with patch("app.services.embedding_service._get_cohere_client", return_value=mock_client):
        generate_embeddings_batch(texts)

    call_kwargs = mock_client.embed.call_args.kwargs
    assert call_kwargs["input_type"] == "search_document"


def test_generate_embedding_single_returns_first_vector():
    """generate_embedding возвращает первый вектор из батча."""
    mock_client = _make_cohere_client_mock(1)

    with patch("app.services.embedding_service._get_cohere_client", return_value=mock_client):
        result = generate_embedding("тест", input_type="search_query")

    assert len(result) == DIM


def test_no_api_key_raises():
    """COHERE_API_KEY не задан → EmbeddingUnavailableError."""
    with patch("app.services.embedding_service._get_cohere_client",
               side_effect=EmbeddingUnavailableError("COHERE_API_KEY не настроен")):
        with pytest.raises(EmbeddingUnavailableError, match="COHERE_API_KEY"):
            generate_embedding("тест")
