"""
Сервис для генерации embedding-векторов через OpenAI.

Используется для семантического поиска по прайс-листу без вызовов Claude.
Векторы генерируются один раз при загрузке прайса и хранятся в БД.
"""
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSION = 1536
OPENAI_BATCH_LIMIT = 2048  # максимум текстов за один API-вызов


class EmbeddingUnavailableError(Exception):
    """OpenAI недоступен или ключ не настроен."""


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

    # Замена латинских букв, совпадающих с кириллическими
    _lat_to_cyr = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
                                 "АВСDЕFGНIЈКLМNОРQRЅТUVWХYZавсdеfgнiјкlмnорqrѕтuvwхyz")
    # Только те буквы, которые реально совпадают визуально
    _simple_lat_cyr = {
        'A': 'А', 'B': 'В', 'C': 'С', 'E': 'Е', 'H': 'Н', 'K': 'К',
        'M': 'М', 'O': 'О', 'P': 'Р', 'T': 'Т', 'X': 'Х',
        'a': 'а', 'c': 'с', 'e': 'е', 'o': 'о', 'p': 'р', 'x': 'х',
    }
    result = "".join(_simple_lat_cyr.get(ch, ch) for ch in text)

    # Нормализация марок: "М-100", "М 100", "М defi 100", "М_100" → "М100"
    # Паттерн: буква (кир или лат), затем необязательный разделитель и слова, затем число
    result = re.sub(
        r'([А-ЯЁа-яёA-Za-z])\s*[-_]?\s*(?:[a-zA-Zа-яА-ЯёЁ]+\s+)*(\d+)',
        lambda m: m.group(1).upper() + m.group(2),
        result
    )

    # Убираем лишние пробелы
    result = " ".join(result.split())

    return result.lower()


def _get_openai_client():
    """Создаёт OpenAI клиент. Бросает EmbeddingUnavailableError если ключ не задан."""
    try:
        from openai import OpenAI, APIError, APIConnectionError
        from app.config import settings

        if not settings.OPENAI_API_KEY:
            raise EmbeddingUnavailableError("OPENAI_API_KEY не настроен")

        return OpenAI(api_key=settings.OPENAI_API_KEY)
    except ImportError:
        raise EmbeddingUnavailableError("Библиотека openai не установлена")


def generate_embedding(text: str) -> list[float]:
    """
    Генерирует embedding-вектор для одного текста.

    Возвращает список из 1536 float.
    Бросает EmbeddingUnavailableError при ошибке API.
    """
    results = generate_embeddings_batch([text])
    return results[0]


def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """
    Генерирует embedding-векторы для списка текстов.

    Автоматически разбивает на чанки по OPENAI_BATCH_LIMIT (2048).
    Возвращает список векторов в том же порядке что и входные тексты.
    Бросает EmbeddingUnavailableError при ошибке API.
    """
    if not texts:
        return []

    try:
        from openai import APIError, APIConnectionError, AuthenticationError
        client = _get_openai_client()

        all_embeddings: list[list[float]] = []

        for chunk_start in range(0, len(texts), OPENAI_BATCH_LIMIT):
            chunk = texts[chunk_start: chunk_start + OPENAI_BATCH_LIMIT]
            response = client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=chunk,
            )
            # Ответ содержит данные в том же порядке что входные тексты
            chunk_embeddings = [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
            all_embeddings.extend(chunk_embeddings)

        return all_embeddings

    except EmbeddingUnavailableError:
        raise
    except Exception as e:
        logger.error("Ошибка OpenAI embeddings API: %s", e)
        raise EmbeddingUnavailableError(f"Ошибка OpenAI API: {e}") from e
