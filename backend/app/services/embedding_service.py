"""
Сервис для генерации embedding-векторов через Cohere.

Используется для семантического поиска по прайс-листу.
Векторы генерируются один раз при загрузке прайса и хранятся в БД.
"""
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "embed-multilingual-v3.0"
EMBEDDING_DIMENSION = 1024
COHERE_BATCH_LIMIT = 96  # максимум текстов за один API-вызов для v3 моделей


class EmbeddingUnavailableError(Exception):
    """Cohere недоступен или ключ не настроен."""


def normalize_name(text: str) -> str:
    """
    Нормализует название позиции перед генерацией embedding.

    Применять одинаково и при загрузке прайса, и при поиске из сметы.

    Правила:
    - Латинские буквы, визуально совпадающие с кириллическими → кириллица
    - Марки материалов: М-100, M defi 100, м 100 → М100
    - Двойные пробелы убираются, текст trim-ится
    - Результат — нижний регистр для сравнения
    """
    if not text:
        return ""

    _simple_lat_cyr = {
        'A': 'А', 'B': 'В', 'C': 'С', 'E': 'Е', 'H': 'Н', 'K': 'К',
        'M': 'М', 'O': 'О', 'P': 'Р', 'T': 'Т', 'X': 'Х',
        'a': 'а', 'c': 'с', 'e': 'е', 'o': 'о', 'p': 'р', 'x': 'х',
    }
    result = "".join(_simple_lat_cyr.get(ch, ch) for ch in text)

    result = re.sub(
        r'([А-ЯЁа-яёA-Za-z])\s*[-_]?\s*(?:[a-zA-Zа-яА-ЯёЁ]+\s+)*(\d+)',
        lambda m: m.group(1).upper() + m.group(2),
        result
    )

    result = " ".join(result.split())
    return result.lower()


def _get_cohere_client():
    """Создаёт Cohere клиент. Бросает EmbeddingUnavailableError если ключ не задан."""
    try:
        import cohere
        from app.config import settings

        if not settings.COHERE_API_KEY:
            raise EmbeddingUnavailableError("COHERE_API_KEY не настроен")

        return cohere.Client(api_key=settings.COHERE_API_KEY)
    except ImportError:
        raise EmbeddingUnavailableError("Библиотека cohere не установлена")


def generate_embedding(text: str, input_type: str = "search_document") -> list[float]:
    """
    Генерирует embedding-вектор для одного текста.

    input_type: "search_document" при индексации, "search_query" при поиске.
    Возвращает список из 1024 float.
    Бросает EmbeddingUnavailableError при ошибке API.
    """
    results = generate_embeddings_batch([text], input_type=input_type)
    return results[0]


def generate_embeddings_batch(
    texts: list[str],
    input_type: str = "search_document",
) -> list[list[float]]:
    """
    Генерирует embedding-векторы для списка текстов.

    input_type: "search_document" при индексации прайса, "search_query" при поиске запроса.
    Автоматически разбивает на чанки по COHERE_BATCH_LIMIT (96).
    Возвращает список векторов в том же порядке что и входные тексты.
    Бросает EmbeddingUnavailableError при ошибке API.
    """
    if not texts:
        return []

    try:
        client = _get_cohere_client()
        all_embeddings: list[list[float]] = []

        for chunk_start in range(0, len(texts), COHERE_BATCH_LIMIT):
            chunk = texts[chunk_start: chunk_start + COHERE_BATCH_LIMIT]
            response = client.embed(
                texts=chunk,
                model=EMBEDDING_MODEL,
                input_type=input_type,
                embedding_types=["float"],
            )
            all_embeddings.extend(response.embeddings.float_)

        return all_embeddings

    except EmbeddingUnavailableError:
        raise
    except Exception as e:
        logger.error("Ошибка Cohere embeddings API: %s", e)
        raise EmbeddingUnavailableError(f"Ошибка Cohere API: {e}") from e
