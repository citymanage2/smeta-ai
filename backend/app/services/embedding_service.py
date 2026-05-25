"""
Сервис для генерации embedding-векторов через FastEmbed (intfloat/multilingual-e5-base).

Используется для семантического поиска по прайс-листу.
Векторы генерируются один раз при загрузке прайса и хранятся в БД.
"""
import re
import threading
import logging

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "intfloat/multilingual-e5-base"
EMBEDDING_DIMENSION = 768

# Singleton с thread-safe reload
_model = None
_model_type: str = "fastembed"  # "fastembed" | "sentence_transformers"
_model_lock = threading.Lock()
_current_model_path: str = EMBEDDING_MODEL


class EmbeddingUnavailableError(Exception):
    """FastEmbed недоступен или модель не загружена."""


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


def _get_model():
    global _model, _model_type
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        try:
            from fastembed import TextEmbedding
            _model = TextEmbedding(_current_model_path)
            _model_type = "fastembed"
            return _model
        except ImportError:
            raise EmbeddingUnavailableError("Библиотека fastembed не установлена")
        except Exception as e:
            raise EmbeddingUnavailableError(f"Не удалось загрузить модель: {e}") from e


def reload_model(model_path: str, model_type: str = "sentence_transformers") -> None:
    """Перезагрузить модель после дообучения без рестарта сервера.

    model_type: "sentence_transformers" — для дообученной модели из /tmp,
                "fastembed" — для возврата на базовую ONNX-модель.
    """
    global _model, _current_model_path, _model_type
    with _model_lock:
        try:
            if model_type == "sentence_transformers":
                from sentence_transformers import SentenceTransformer
                _model = SentenceTransformer(model_path)
            else:
                from fastembed import TextEmbedding
                _model = TextEmbedding(model_path)
            _current_model_path = model_path
            _model_type = model_type
        except Exception as e:
            raise EmbeddingUnavailableError(f"Не удалось перезагрузить модель: {e}") from e


def generate_embedding(text: str, input_type: str = "search_document") -> list[float]:
    """
    Генерирует embedding-вектор для одного текста.

    input_type: "search_document" при индексации, "search_query" при поиске.
    Возвращает список из 768 float.
    Бросает EmbeddingUnavailableError при ошибке.
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
    multilingual-e5 требует префикс passage:/query: для точного матчинга.
    Возвращает список векторов в том же порядке что и входные тексты.
    Бросает EmbeddingUnavailableError при ошибке.
    """
    if not texts:
        return []

    try:
        prefix = "passage: " if input_type == "search_document" else "query: "
        prefixed = [prefix + normalize_name(t) for t in texts]
        model = _get_model()
        if _model_type == "sentence_transformers":
            embeddings = model.encode(prefixed, normalize_embeddings=True, show_progress_bar=False)
            return [e.tolist() for e in embeddings]
        else:
            embeddings = list(model.embed(prefixed))
            return [e.tolist() for e in embeddings]
    except EmbeddingUnavailableError:
        raise
    except Exception as e:
        logger.error("Ошибка embedding: %s", e)
        raise EmbeddingUnavailableError(f"Ошибка embedding: {e}") from e
