"""Unit tests for embedding_service: normalize_name (8.1) and generate_embeddings_batch (8.2)."""
import sys
import pytest
from unittest.mock import patch, MagicMock

# Mock the openai module before importing embedding_service functions
# so tests run without the openai package installed
_openai_mock = MagicMock()
_openai_mock.APIError = Exception
_openai_mock.APIConnectionError = Exception
_openai_mock.AuthenticationError = Exception
sys.modules.setdefault("openai", _openai_mock)

from app.services.embedding_service import (
    normalize_name,
    generate_embeddings_batch,
    EmbeddingUnavailableError,
)


# ---------------------------------------------------------------------------
# 8.1: normalize_name
# ---------------------------------------------------------------------------

def test_normalize_m_defi_100():
    """'M defi 100' нормализуется в 'м100'."""
    assert normalize_name("M defi 100") == "м100"


def test_normalize_m_dash_50():
    """'М-50' нормализуется в 'м50'."""
    assert normalize_name("М-50") == "м50"


def test_normalize_extra_spaces():
    """Лишние пробелы убираются."""
    assert normalize_name("  Кладка  кирпичная  ") == "кладка кирпичная"


def test_normalize_empty_string():
    assert normalize_name("") == ""


def test_normalize_m100_lowercase():
    """'М100' → 'м100'."""
    assert normalize_name("М100") == "м100"


def test_normalize_m_defi_100_equals_m100():
    """'M defi 100' и 'М100' дают одинаковый результат — должны совпасть при поиске."""
    assert normalize_name("M defi 100") == normalize_name("М100")


def test_normalize_m100_not_equals_m50():
    """'М100' и 'М50' нормализуются по-разному — не должны перепутаться."""
    assert normalize_name("М100") != normalize_name("М50")


def test_normalize_latin_m_to_cyrillic():
    """Латинская M заменяется на кириллическую М."""
    result = normalize_name("M100")
    assert result == "м100"


# ---------------------------------------------------------------------------
# 8.2: generate_embeddings_batch
# ---------------------------------------------------------------------------

def _mock_openai_response(count: int, dim: int = 1536) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.data = [
        MagicMock(index=i, embedding=[float(i % 10) / 10.0 + 0.1] * dim)
        for i in range(count)
    ]
    return mock_resp


def test_generate_embeddings_batch_success():
    """Успешная генерация: возвращает вектор для каждого текста."""
    texts = ["кладка кирпичная", "штукатурка", "бетонирование"]
    mock_client = MagicMock()
    mock_client.embeddings.create.return_value = _mock_openai_response(len(texts))

    with patch("app.services.embedding_service._get_openai_client", return_value=mock_client):
        result = generate_embeddings_batch(texts)

    assert len(result) == 3
    assert all(len(v) == 1536 for v in result)
    mock_client.embeddings.create.assert_called_once()


def test_generate_embeddings_batch_empty_input():
    """Пустой список → пустой результат без вызовов API."""
    result = generate_embeddings_batch([])
    assert result == []


def test_generate_embeddings_batch_api_error_raises():
    """Любая ошибка OpenAI API → EmbeddingUnavailableError."""
    mock_client = MagicMock()
    mock_client.embeddings.create.side_effect = RuntimeError("connection timeout")

    with patch("app.services.embedding_service._get_openai_client", return_value=mock_client):
        with pytest.raises(EmbeddingUnavailableError):
            generate_embeddings_batch(["тест"])


def test_generate_embeddings_batch_returns_in_order():
    """Векторы возвращаются в том же порядке, что входные тексты."""
    texts = ["первый", "второй", "третий"]
    mock_client = MagicMock()
    # Специально перемешиваем порядок в ответе — должны быть отсортированы по index
    resp = MagicMock()
    resp.data = [
        MagicMock(index=2, embedding=[2.0] * 1536),
        MagicMock(index=0, embedding=[0.0] * 1536),
        MagicMock(index=1, embedding=[1.0] * 1536),
    ]
    mock_client.embeddings.create.return_value = resp

    with patch("app.services.embedding_service._get_openai_client", return_value=mock_client):
        result = generate_embeddings_batch(texts)

    assert result[0][0] == 0.0  # index=0
    assert result[1][0] == 1.0  # index=1
    assert result[2][0] == 2.0  # index=2
